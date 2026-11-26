from odoo import fields, models


class PaymentMethod(models.Model):
    _inherit = "payment.method"

    modena_maturity_months = fields.Integer(
        string="Term (months)",
        help="Financing term sent to Modena. Leave empty to let Modena use its default."
        " Operating lease accepts 12, 24 or 36.",
    )
    modena_min_amount = fields.Float(string="Minimum Amount")
    modena_max_amount = fields.Float(string="Maximum Amount")

    def _modena_filter_available(self, amount, currency, order):
        def available(method):
            if method.provider_id.code != "modena":
                return True
            if not method._modena_is_available_for(amount, currency):
                return False
            if method.code == "modena_operating_lease":
                lines = order and order.order_line.filtered(lambda l: not l.display_type)
                return bool(lines) and all(
                    l.product_id.product_tmpl_id.modena_asset_catalog_entry_id for l in lines
                )
            return True

        return self.filtered(available)

    def _modena_is_available_for(self, amount, currency):
        self.ensure_one()
        if self.modena_min_amount and currency.compare_amounts(amount, self.modena_min_amount) < 0:
            return False
        if self.modena_max_amount and currency.compare_amounts(amount, self.modena_max_amount) > 0:
            return False
        return True
