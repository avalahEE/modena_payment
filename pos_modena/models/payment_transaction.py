from odoo import models


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    def _apply_updates(self, payment_data):
        super()._apply_updates(payment_data)
        if self.provider_code == "modena" and self.pos_order_id and self.state in ("cancel", "error"):
            self._modena_notify_pos("rejected")

    def _process_pos_online_payment(self):
        closed = self.filtered(lambda tx: tx.pos_order_id.session_id.state == "closed")
        for tx in closed:
            # The till is closed: keep the money as a customer payment and let accounting finish it.
            message = self.env._(
                "Payment %(ref)s arrived after the POS session %(session)s was closed. The payment"
                " is booked as a customer payment, finish order %(order)s manually.",
                ref=tx.reference,
                session=tx.pos_order_id.session_id.name,
                order=tx.pos_order_id.name,
            )
            tx.pos_order_id.message_post(body=message)
            if tx.payment_id:
                tx.payment_id.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=self.env._("Online payment after POS closing"),
                    note=message,
                    user_id=tx.pos_order_id.user_id.id or self.env.ref("base.user_admin").id,
                )
        open_txs = self - closed
        super(PaymentTransaction, open_txs)._process_pos_online_payment()
        for tx in open_txs.filtered(lambda t: t.pos_order_id and t.state in ("authorized", "done")):
            tx._modena_notify_pos("paid")

    def _modena_notify_pos(self, status):
        order = self.pos_order_id
        order.config_id._notify("MODENA_POS_PAYMENT", {
            "id": order.id,
            "name": order.tracking_number or order.name,
            "status": status,
        })
