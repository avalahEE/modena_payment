from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    modena_asset_catalog_entry_id = fields.Char(
        string="Modena Asset Catalog ID",
        help="Asset catalog entry agreed with Modena. Required to sell the product on operating lease.",
    )
    modena_buyback_percentage = fields.Float(
        string="Modena Buyback %",
        help="Buyback value at the end of the operating lease, as a percentage of the net price.",
    )
