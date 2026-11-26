from odoo import api, fields, models


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    modena_payment_slip = fields.Boolean(
        string="Print payment slip",
        default=True,
        help="Offer to print a slip with the customer's own payment QR code, so they can pay on"
        " their phone while the till serves the next customer.",
    )
    modena_slip_minutes = fields.Integer(
        string="Slip valid for (minutes)",
        default=30,
        help="How long the customer has to start the payment. After that the parked order is"
        " cancelled and its reserved products are released.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ["modena_payment_slip", "modena_slip_minutes"]
