from odoo import api, models


class IrUiView(models.Model):
    _inherit = "ir.ui.view"

    @api.model
    def _get_xml_ids_to_load(self):
        return super()._get_xml_ids_to_load() + ["pos_modena.payment_slip"]
