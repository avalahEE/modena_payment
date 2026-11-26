from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.pos_online_payment.controllers.payment_portal import PaymentPortal


class ModenaPosPaymentPortal(PaymentPortal):

    def _check_order_access(self, pos_order_id, access_token):
        expired = ValidationError(request.env._(
            "The time to pay this order has ended. Please contact the shop."
        ))
        try:
            order_sudo = super()._check_order_access(pos_order_id, access_token)
        except ValidationError:
            # The token was valid; the order was cancelled, maybe by the expiry cron.
            order_sudo = request.env["pos.order"].sudo().browse(pos_order_id)
            if order_sudo.modena_parked_until:
                raise expired from None
            raise
        if order_sudo._modena_expired():
            raise expired
        return order_sudo

    def _render_pay(self, rendering_context):
        order_id = rendering_context.get("pos_order_id")
        if order_id:
            rendering_context["pos_order_sudo"] = request.env["pos.order"].sudo().browse(order_id)
        return super()._render_pay(rendering_context)
