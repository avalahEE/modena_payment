import time

import requests

from odoo import api, fields, models, release
from odoo.exceptions import ValidationError
from odoo.tools.binary import BinaryBytes

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_modena import const

_logger = get_payment_logger(__name__)

# ponytail: per-process token cache, every worker fetches its own 5-minute token
_token_cache = {}


class PaymentProvider(models.Model):
    _inherit = "payment.provider"

    code = fields.Selection(
        selection_add=[("modena", "Modena")], ondelete={"modena": "set default"}
    )
    modena_client_id = fields.Char(
        string="Modena Client ID",
        help="Modena Portal > Modena Konto > Arendajale > API võtmed",
        required_if_provider="modena",
        copy=False,
        groups="base.group_system",
    )
    modena_client_secret = fields.Char(
        string="Modena Client Secret",
        required_if_provider="modena",
        copy=False,
        groups="base.group_system",
    )
    modena_signature_key = fields.Char(
        string="Modena Signature Key",
        help="Used to verify the signature of Modena bank payment notifications.",
        copy=False,
        groups="base.group_system",
    )

    def _get_supported_currencies(self):
        supported_currencies = super()._get_supported_currencies()
        if self.code == "modena":
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES
            )
        return supported_currencies

    def _get_default_payment_method_codes(self):
        self.ensure_one()
        if self.code != "modena":
            return super()._get_default_payment_method_codes()
        return const.DEFAULT_PAYMENT_METHOD_CODES

    def _find_available_payment_methods(self, partner_id, *args, **kwargs):
        methods = super()._find_available_payment_methods(partner_id, *args, **kwargs)
        partner = self.env["res.partner"].browse(partner_id)
        if not partner.country_id and self.env.company.country_id:
            # Anonymous POS and portal payers have no country: show the local banks only.
            country = self.env.company.country_id
            methods = methods.filtered(
                lambda m: m.provider_id.code != "modena"
                or not m.supported_country_ids
                or country in m.supported_country_ids
            )
        if not (partner.email and partner.phone):
            # Financing needs both to open an application, bank payments do not.
            methods = methods.filtered(
                lambda m: m.provider_id.code != "modena" or m.code.startswith(const.DIRECT_PREFIX)
            )
        return methods

    # === REQUESTS === #

    def _modena_get_access_token(self, scope):
        self.ensure_one()
        sudo = self.sudo()
        key = (self.id, self.is_live, sudo.modena_client_id, scope)
        token, expires_at = _token_cache.get(key, (None, 0))
        if token and expires_at > time.time():
            return token

        try:
            response = requests.post(
                const.TOKEN_URL[self.is_live],
                auth=(sudo.modena_client_id, sudo.modena_client_secret),
                data={"grant_type": "client_credentials", "scope": scope},
                timeout=10,
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            raise ValidationError(self.env._("Could not establish the connection to Modena.")) from None
        if not response.ok:
            _logger.error("Modena token request for scope %s failed: %s", scope, response.text)
            raise ValidationError(
                self.env._("Modena rejected the API credentials (HTTP %s).", response.status_code)
            )
        data = response.json()
        _token_cache[key] = (data["access_token"], time.time() + data.get("expires_in", 299) - 30)
        return data["access_token"]

    def _modena_send_request(self, method, path, scope, *, json=None, reference=None):
        """Call the Modena API without following redirects.

        Order creation answers with 302, the redirect target is returned under `location`.
        """
        self.ensure_one()
        url = f"{const.API_URL[self.is_live]}/{path}"
        module_version = self.env.ref("base.module_payment_modena").installed_version
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._modena_get_access_token(scope)}",
            "User-Agent": f"ModenaOdoo/{module_version} Odoo/{release.version}",
        }
        self._log_request(method, url, json, reference=reference)
        try:
            response = requests.request(
                method, url, json=json, headers=headers, allow_redirects=False, timeout=10
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            raise ValidationError(self.env._("Could not establish the connection to Modena.")) from None
        self._log_response(response, reference=reference)

        if response.status_code >= 400:
            raise ValidationError(
                self.env._(
                    "Modena rejected the request.\n%s", self._modena_parse_error(response)
                )
            )
        data = response.json() if response.content else {}
        if response.status_code in (301, 302, 303):
            data["location"] = response.headers.get("Location")
        return data

    def _modena_parse_error(self, response):
        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError:
            return response.text or str(response.status_code)
        errors = ", ".join(f"{e.get('field')}: {e.get('message')}" for e in data.get("errors") or [])
        return " ".join(filter(None, [data.get("detail") or data.get("title"), errors])) or str(
            response.status_code
        )

    # === BANKS === #

    def action_modena_sync_banks(self):
        for provider in self.filtered(lambda p: p.code == "modena"):
            provider._modena_sync_banks()

    def _modena_sync_banks(self):
        self.ensure_one()
        countries = self._modena_send_request(
            "GET", "direct/api/partner-direct-payments/payment-methods", const.DIRECT_SCOPE
        )
        banks = {}
        for country_code, country_data in countries.items():
            for option in country_data.get("paymentMethods", []):
                bank = banks.setdefault(option["code"], {**option, "countries": set()})
                bank["countries"].add(country_code)

        Method = self.env["payment.method"].with_context(active_test=False)
        existing = Method.search([
            ("provider_id", "=", self.id), ("code", "=like", f"{const.DIRECT_PREFIX}%")
        ])
        eur = self.env.ref("base.EUR")
        seen = Method
        for option_code, bank in banks.items():
            code = const.DIRECT_PREFIX + option_code.lower()
            method = existing.filtered(lambda m: m.code == code)
            values = {
                "name": bank["name"],
                "sequence": 100 + (bank.get("order") or 0),
                "supported_country_ids": [
                    fields.Command.set(
                        self.env["res.country"].search([("code", "in", list(bank["countries"]))]).ids
                    )
                ],
                "supported_currency_ids": [fields.Command.set(eur.ids)],
            }
            image = self._modena_fetch_image(bank.get("buttonUrl"))
            if image:
                values["image"] = image
            if method:
                method.write(values)
            else:
                method = Method.create({
                    "code": code,
                    "provider_id": self.id,
                    "active": False,
                    "image": image or self._modena_default_image(),
                    **values,
                })
            seen |= method
        (existing - seen).active = False

    def _modena_fetch_image(self, url):
        if not url:
            return False
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException:
            _logger.warning("Could not download the Modena bank logo %s", url)
            return False
        return BinaryBytes(response.content)

    def _modena_default_image(self):
        return self.env.ref("payment_modena.payment_method_modena_slice").image

    @api.model
    def _cron_modena_sync_banks(self):
        providers = self.search([("code", "=", "modena")]).filtered(
            lambda p: p.sudo().modena_client_id and p.payment_method_ids.filtered(
                lambda m: m.code.startswith(const.DIRECT_PREFIX)
            )
        )
        for provider in providers:
            try:
                provider._modena_sync_banks()
            except ValidationError:
                _logger.exception("Modena bank list update failed for provider %s", provider.id)
