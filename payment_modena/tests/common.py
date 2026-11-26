import json
from unittest.mock import Mock, patch

from odoo.fields import Command

from odoo.addons.payment.tests.common import PaymentCommon

PROVIDER_PATH = "odoo.addons.payment_modena.models.payment_provider"


def mock_response(status=200, data=None, headers=None):
    body = json.dumps(data).encode() if data is not None else b""
    return Mock(
        status_code=status,
        ok=status < 400,
        reason="",
        url="https://api-dev.modena.ee/mock",
        headers=headers or {},
        content=body,
        text=body.decode(),
        json=Mock(return_value=data),
    )


class ModenaCommon(PaymentCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls._prepare_provider("modena", update_values={
            "modena_client_id": "client",
            "modena_client_secret": "secret",
            "modena_signature_key": "68de6cbe-395d-49d0-85a7-ed5995794aef",
        })
        cls.currency = cls.currency_euro
        cls.provider.payment_method_ids.active = True
        cls.slice = cls.env.ref("payment_modena.payment_method_modena_slice")
        cls.lease = cls.env.ref("payment_modena.payment_method_modena_operating_lease")
        cls.payment_method = cls.slice
        cls.payment_method_id = cls.slice.id
        cls.application_id = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        cls.payment_data = {"id": cls.application_id, "orderId": cls.reference}

        cls.tax = cls.env["account.tax"].create({
            "name": "VAT 24", "amount": 24, "amount_type": "percent", "type_tax_use": "sale",
        })
        cls.product = cls.env["product.product"].create({
            "name": "Sofa", "list_price": 100, "taxes_id": [Command.set(cls.tax.ids)],
        })

    def setUp(self):
        super().setUp()
        self.token_patcher = patch(
            f"{PROVIDER_PATH}.PaymentProvider._modena_get_access_token", return_value="token"
        )
        self.token_patcher.start()
        self.addCleanup(patch.stopall)

    def _create_order(self, qty=2, product=None):
        if "sale.order" not in self.env:
            self.skipTest("sale is not installed")
        return self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [Command.create({
                "product_id": (product or self.product).id,
                "product_uom_qty": qty,
                "price_unit": 100,
                "tax_ids": [Command.set(self.tax.ids)],
            })],
        })

    def _create_order_tx(self, order, method=None, **values):
        return self._create_transaction(
            "redirect",
            amount=order.amount_total,
            payment_method_id=(method or self.slice).id,
            sale_order_ids=[Command.set(order.ids)],
            **values,
        )
