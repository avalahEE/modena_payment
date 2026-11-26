from datetime import UTC, datetime, timedelta

import phonenumbers

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import urls

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_modena import const
from odoo.addons.payment_modena.controllers.main import ModenaController

_logger = get_payment_logger(__name__)


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    def _modena_is_direct(self):
        return (self.payment_method_code or "").startswith(const.DIRECT_PREFIX)

    def _modena_scope(self):
        if self._modena_is_direct():
            return const.DIRECT_SCOPE
        return const.FINANCING_PRODUCTS[self.payment_method_code][1]

    # === ORDER CREATION === #

    def _get_specific_rendering_values(self, processing_values):
        if self.provider_code != "modena":
            return super()._get_specific_rendering_values(processing_values)

        try:
            if self._modena_is_direct():
                path = "direct/api/partner-direct-payments/payment-order"
                payload = self._modena_prepare_direct_payload()
            else:
                endpoint = const.FINANCING_PRODUCTS[self.payment_method_code][0]
                path = f"modena/api/merchant/{endpoint}"
                if self.payment_method_code == "modena_operating_lease":
                    payload = self._modena_prepare_operating_lease_payload()
                else:
                    payload = self._modena_prepare_financing_payload()
            data = self.provider_id._modena_send_request(
                "POST", path, self._modena_scope(), json=payload, reference=self.reference
            )
        except ValidationError as error:
            self._set_error(str(error))
            return {}

        self.provider_reference = data.get("id")
        url = data.get("onboardingUrl") or data.get("location")
        return {
            "api_url": url,
            "http_method": "get",
            "url_params": payment_utils.extract_url_params(url),
        }

    def _modena_common_payload(self):
        base_url = self.provider_id.get_base_url()
        return {
            "orderId": self.reference,
            "currency": self.currency_id.name,
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "returnUrl": urls.urljoin(base_url, ModenaController._return_url),
            "cancelUrl": urls.urljoin(base_url, ModenaController._cancel_url),
            "callbackUrl": urls.urljoin(base_url, ModenaController._webhook_url),
        }

    def _modena_customer(self):
        first_name, last_name = payment_utils.split_partner_name(self.partner_name or "")
        address = ", ".join(filter(None, [
            self.partner_address, " ".join(filter(None, [self.partner_zip, self.partner_city]))
        ]))
        return {
            "firstName": first_name,
            "lastName": last_name,
            "email": self.partner_email or "",
            "phoneNumber": self._modena_phone(),
            "address": address,
        }

    def _modena_phone(self):
        phone = (self.partner_phone or "").strip()
        if not phone:
            return ""
        try:
            number = phonenumbers.parse(phone, self.partner_country_id.code or "EE")
        except phonenumbers.NumberParseException:
            return phone
        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)

    def _modena_country(self, allowed):
        code = self.partner_country_id.code
        return code if code in allowed else "EE"

    def _modena_documents(self):
        # sale, account_payment and pos_online_payment are all optional
        return [
            *getattr(self, "sale_order_ids", []),
            *getattr(self, "invoice_ids", []),
            *getattr(self, "pos_order_id", []),
        ]

    def _modena_order_lines(self):
        """(description, qty, total, subtotal, taxes) of the one document the tx pays in full."""
        documents = self._modena_documents()
        if len(documents) != 1:
            return None
        doc = documents[0]
        if doc.currency_id.compare_amounts(doc.amount_total, self.amount):
            return None
        if doc._name == "sale.order":
            return [
                (l.name or l.product_id.display_name, l.product_uom_qty, l.price_total, l.price_subtotal, l.tax_ids)
                for l in doc.order_line if not l.display_type
            ]
        if doc._name == "account.move":
            return [
                (l.name or l.product_id.display_name, l.quantity, l.price_total, l.price_subtotal, l.tax_ids)
                for l in doc.invoice_line_ids if l.display_type == "product"
            ]
        return [
            (l.full_product_name or l.product_id.display_name, l.qty, l.price_subtotal_incl, l.price_subtotal, l.tax_ids)
            for l in doc.lines
        ]

    def _modena_financing_items(self):
        currency = self.currency_id
        items = []
        lines = self._modena_order_lines()
        for name, qty, total, subtotal, taxes in lines or []:
            if not total:
                continue
            if qty <= 0 or qty != int(qty) or total < 0:
                items = None
                break
            item = {
                "description": name.split("\n")[0][:255],
                "amount": currency.round(total / qty),
                "currency": currency.name,
                "quantity": int(qty),
                "netAmount": currency.round(subtotal / qty),
                "taxAmount": currency.round((total - subtotal) / qty),
            }
            if len(taxes) == 1 and taxes.amount_type == "percent":
                item["taxRate"] = taxes.amount
            items.append(item)

        if items and not currency.compare_amounts(
            sum(i["amount"] * i["quantity"] for i in items), self.amount
        ):
            return items
        return [{
            "description": self.reference,
            "amount": self.amount,
            "currency": currency.name,
            "quantity": 1,
        }]

    def _modena_check_contact(self, customer):
        if not customer["email"] or not customer["phoneNumber"]:
            raise ValidationError(
                self.env._("Modena requires the customer's email address and phone number.")
            )

    def _modena_prepare_financing_payload(self):
        customer = self._modena_customer()
        self._modena_check_contact(customer)
        items = self._modena_financing_items()
        payload = {
            **self._modena_common_payload(),
            "country": self._modena_country(const.FINANCING_COUNTRIES),
            "totalAmount": self.amount,
            "description": self.reference,
            "orderItems": items,
            "customer": customer,
        }
        if all("netAmount" in i for i in items):
            net = sum(i["netAmount"] * i["quantity"] for i in items)
            payload["totalNetAmount"] = self.currency_id.round(net)
            payload["totalTaxAmount"] = self.currency_id.round(self.amount - net)
        if self.payment_method_id.modena_maturity_months:
            payload["maturityInMonths"] = self.payment_method_id.modena_maturity_months
        return payload

    def _modena_prepare_operating_lease_payload(self):
        customer = self._modena_customer()
        self._modena_check_contact(customer)
        term = self.payment_method_id.modena_maturity_months
        if term not in const.OPERATING_LEASE_TERMS:
            raise ValidationError(self.env._("Modena operating lease term must be 12, 24 or 36 months."))
        orders = getattr(self, "sale_order_ids", [])
        if len(orders) != 1:
            raise ValidationError(self.env._("Modena operating lease is only available for a sale order."))

        currency = self.currency_id
        items = []
        for line in orders.order_line.filtered(lambda l: not l.display_type):
            template = line.product_id.product_tmpl_id
            qty = line.product_uom_qty
            if not template.modena_asset_catalog_entry_id or qty <= 0 or qty != int(qty):
                raise ValidationError(
                    self.env._("%s cannot be sold on Modena operating lease.", line.product_id.display_name)
                )
            taxes = line.tax_ids.filtered(lambda t: t.amount_type == "percent")
            for i in range(int(qty)):
                items.append({
                    "assetName": line.product_id.display_name,
                    "assetCatalogEntryId": template.modena_asset_catalog_entry_id,
                    "assetIdentifier": f"{self.reference}-{line.id}-{i + 1}",
                    "netPriceAmount": currency.round(line.price_subtotal / qty),
                    "vatPercentage": sum(taxes.mapped("amount")),
                    "vatAmount": currency.round((line.price_total - line.price_subtotal) / qty),
                    "buybackPercentage": template.modena_buyback_percentage,
                })
        return {
            **self._modena_common_payload(),
            "maturityInMonths": term,
            "orderItems": items,
            "customer": customer,
        }

    def _modena_prepare_direct_payload(self):
        customer = self._modena_customer()
        if not customer["lastName"]:
            customer["lastName"] = customer["firstName"]
        lang = (self.partner_lang or self.env.lang or "et").split("_")[0].upper()
        return {
            **self._modena_common_payload(),
            "selectedOption": self.payment_method_code.removeprefix(const.DIRECT_PREFIX).upper(),
            "totalAmount": self.amount,
            "orderItems": [
                {k: v for k, v in item.items() if k in ("description", "amount", "currency", "quantity")}
                for item in self._modena_financing_items()
            ],
            "customer": {k: v for k, v in customer.items() if v},
            "language": lang if lang in const.DIRECT_LANGUAGES else "EN",
            "country": self._modena_country(const.DIRECT_COUNTRIES),
        }

    # === STATUS === #

    def _modena_fetch_status(self):
        self.ensure_one()
        if self._modena_is_direct():
            path = f"direct/api/partner-direct-payments/{self.provider_reference}/status"
        else:
            path = f"modena/api/merchant/applications/{self.provider_reference}/status"
        data = self.provider_id._modena_send_request(
            "GET", path, self._modena_scope(), reference=self.reference
        )
        return {**data, "id": self.provider_reference, "orderId": self.reference}

    def _modena_record_status(self, cancelled=False):
        data = self._modena_fetch_status()
        if cancelled:
            data["cancelled_by_customer"] = True
        self._record(data)

    def action_modena_refresh_status(self):
        for tx in self.filtered(lambda t: t.provider_code == "modena" and t.provider_reference):
            tx._modena_record_status()

    @api.model
    def _cron_modena_check_pending(self):
        txs = self.search([
            ("provider_code", "=", "modena"),
            ("state", "in", ("draft", "pending")),
            ("provider_reference", "!=", False),
            ("create_date", ">=", fields.Datetime.now() - timedelta(days=30)),
        ])
        for tx in txs:
            try:
                tx._modena_record_status()
            except ValidationError:
                _logger.warning("Modena status check failed for transaction %s", tx.reference)

    def _modena_notify_late_approval(self):
        message = self.env._(
            "Modena approved payment %(ref)s after the customer had left the application. Check"
            " that the order was not paid twice.",
            ref=self.reference,
        )
        for document in self._modena_documents():
            document.message_post(body=message)
            document.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=self.env._("Modena payment approved late"),
                note=message,
                user_id=document.user_id.id or self.env.ref("base.user_admin").id,
            )

    # === PROCESSING === #

    @api.model
    def _extract_reference(self, provider_code, payment_data):
        if provider_code != "modena":
            return super()._extract_reference(provider_code, payment_data)
        return payment_data.get("orderId")

    def _extract_amount_data(self, payment_data):
        if self.provider_code != "modena":
            return super()._extract_amount_data(payment_data)
        return None  # The status endpoint returns no amount; the amount is ours, sent on creation.

    def _apply_updates(self, payment_data):
        if self.provider_code != "modena":
            return super()._apply_updates(payment_data)

        status = payment_data.get("status")
        if status == "OUTSTANDING" and payment_data.get("cancelled_by_customer"):
            self._set_canceled(self.env._(
                "The customer left the Modena application. If they complete it later, the payment"
                " is confirmed automatically."
            ))
        elif status in const.STATUS_MAPPING["pending"]:
            message = None
            if status == "IN_MANUAL_REVIEW":
                message = self.env._("Modena is reviewing the application.")
            self._set_pending(state_message=message, extra_allowed_states=("pending",))
        elif status in const.STATUS_MAPPING["done"]:
            # The customer may come back through the cancel URL and get approved later.
            was_cancelled = self.state == "cancel"
            self._set_done(extra_allowed_states=("cancel",))
            if was_cancelled:
                self._modena_notify_late_approval()
        elif status in const.STATUS_MAPPING["cancel"]:
            self._set_canceled(self.env._("Modena application status: %s", status))
        elif status in const.STATUS_MAPPING["error"]:
            self._set_error(self.env._("Modena could not process the payment."))
        else:
            _logger.warning("Unknown Modena status %s for transaction %s", status, self.reference)
            self._set_error(self.env._("Received an unknown Modena status: %s", status))
