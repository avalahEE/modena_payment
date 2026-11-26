from datetime import timedelta

from odoo import api, fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    modena_parked_until = fields.Datetime(readonly=True, copy=False)
    # Kept apart from picking_ids: pos_stock skips the real delivery when picking_ids is set.
    modena_reservation_id = fields.Many2one("stock.picking", readonly=True, copy=False)

    def action_modena_park(self, minutes):
        self.ensure_one()
        self.modena_parked_until = fields.Datetime.now() + timedelta(minutes=minutes or 30)
        self._modena_reserve()
        return fields.Datetime.to_string(self.modena_parked_until)

    def _modena_reserve(self):
        self.ensure_one()
        if self.modena_reservation_id.state not in (False, "cancel", "done"):
            return
        lines = self.lines.filtered(lambda l: l.product_id.is_storable and l.qty > 0)
        if not lines:
            return
        picking_type = self.config_id.picking_type_id
        source = picking_type.default_location_src_id
        destination = self.partner_id.property_stock_customer or picking_type.default_location_dest_id
        picking = self.env["stock.picking"].sudo().create({
            "picking_type_id": picking_type.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "partner_id": self.partner_id.id,
            "origin": self.env._("%s (waiting for Modena payment)", self.pos_reference or self.tracking_number),
            "move_ids": [
                fields.Command.create({
                    "product_id": line.product_id.id,
                    "product_uom_qty": line.qty,
                    "uom_id": line.product_id.uom_id.id,
                    "location_id": source.id,
                    "location_dest_id": destination.id,
                })
                for line in lines
            ],
        })
        picking.action_confirm()
        picking.action_assign()
        self.modena_reservation_id = picking

    def _modena_release(self):
        reservations = self.modena_reservation_id.filtered(lambda p: p.state not in ("done", "cancel"))
        reservations.sudo().action_cancel()

    def _modena_payment_started(self):
        self.ensure_one()
        return bool(self.env["payment.transaction"].sudo().search_count([
            ("pos_order_id", "=", self.id),
            ("state", "in", ("draft", "pending", "authorized", "done")),
        ], limit=1))

    def _modena_expired(self):
        self.ensure_one()
        return (
            self.state == "draft"
            and self.modena_parked_until
            and self.modena_parked_until < fields.Datetime.now()
            and not self._modena_payment_started()
        )

    def write(self, vals):
        if vals.get("state") and vals["state"] != "draft":
            self.filtered(lambda o: o.state == "draft")._modena_release()
        return super().write(vals)

    def unlink(self):
        self._modena_release()
        return super().unlink()

    @api.model
    def _cron_modena_expire_parked(self):
        orders = self.search([
            ("state", "=", "draft"),
            ("modena_parked_until", "<", fields.Datetime.now()),
        ]).filtered(lambda o: o._modena_expired())
        for order in orders:
            order.with_context(active_ids=order.ids).action_pos_order_cancel()
            order.config_id._notify("MODENA_POS_PAYMENT", {
                "id": order.id,
                "name": order.tracking_number or order.name,
                "status": "expired",
            })
