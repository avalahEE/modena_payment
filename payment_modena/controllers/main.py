import hashlib
import hmac
import pprint

from werkzeug.exceptions import ServiceUnavailable

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.payment.controllers.payment_status import PaymentStatus
from odoo.addons.payment.controllers.portal import PaymentPortal
from odoo.addons.payment.logging import get_payment_logger

_logger = get_payment_logger(__name__)


def modena_signature(key, application_id, order_id):
    return hmac.new(
        key.encode(), f"{application_id}{order_id}".encode(), hashlib.sha256
    ).hexdigest()


class ModenaController(http.Controller):
    _return_url = "/payment/modena/return"
    _cancel_url = "/payment/modena/cancel"
    _webhook_url = "/payment/modena/webhook"

    # save_session=False: Modena comes back with a cross-site POST that may not carry the session
    # cookie, /payment/status then picks the session up again.
    @http.route(
        [_return_url, _cancel_url],
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
        save_session=False,
    )
    def modena_return(self, **data):
        _logger.info("Customer returned from Modena with data:\n%s", pprint.pformat(data))
        cancelled = request.httprequest.path == self._cancel_url
        try:
            if data.get("orderId"):
                self._verify_and_process(data, data.get("digest"), cancelled=cancelled)
            else:
                # The back button on Modena's rejection page returns without any data.
                tx_sudo = request.env["payment.transaction"].sudo().browse(
                    request.session.get(PaymentStatus.MONITORED_TX_ID_KEY)
                ).exists()
                if tx_sudo.provider_code == "modena" and tx_sudo.provider_reference:
                    tx_sudo._modena_record_status(cancelled=cancelled)
        except ValidationError:
            _logger.exception("Unable to process the Modena return")
        return request.redirect("/payment/status")

    # GET too: a proxy that redirects http to https turns the POST into a GET, and the data is
    # only used to look up the status anyway.
    @http.route(_webhook_url, type="http", auth="public", methods=["GET", "POST"], csrf=False)
    def modena_webhook(self, **data):
        signature = request.httprequest.headers.get("X-Modena-Signature")
        _logger.info(
            "Modena notification received (signed: %s) with data:\n%s",
            bool(signature), pprint.pformat(data),
        )
        try:
            self._verify_and_process(data, signature)
        except ValidationError as error:
            raise ServiceUnavailable from error  # Modena retries the notification
        return ""

    @staticmethod
    def _verify_and_process(data, signature, cancelled=False):
        tx_sudo = request.env["payment.transaction"].sudo()._search_by_reference("modena", data)
        if not tx_sudo:
            return
        if not tx_sudo.provider_reference or data.get("id") != tx_sudo.provider_reference:
            _logger.warning("Modena data for %s carries a foreign application id", tx_sudo.reference)
            return

        key = tx_sudo.provider_id.modena_signature_key
        if signature and key and not hmac.compare_digest(
            signature, modena_signature(key, data["id"], data.get("orderId", ""))
        ):
            _logger.warning("Invalid Modena signature for %s", tx_sudo.reference)
            return

        # The notification only says that something changed: the status comes from the API.
        tx_sudo._modena_record_status(cancelled=cancelled)


class ModenaPaymentPortal(PaymentPortal):

    def _prepare_payment_form_values(self, company_id, partner_id, amount, *args, **kwargs):
        values = super()._prepare_payment_form_values(company_id, partner_id, amount, *args, **kwargs)
        methods = values.get("payment_methods_sudo")
        if not methods:
            return values

        currency = request.env["res.currency"].browse(kwargs.get("currency_id")).exists()
        currency = currency or request.env["res.company"].browse(company_id).currency_id
        order = None
        if "sale.order" in request.env and kwargs.get("sale_order_id"):
            order = request.env["sale.order"].sudo().browse(kwargs["sale_order_id"]).exists()

        values["payment_methods_sudo"] = methods._modena_filter_available(amount, currency, order)
        return values
