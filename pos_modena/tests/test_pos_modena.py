from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install")
class TestPosModena(TestPoSCommon, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.provider = cls.env.ref("payment_modena.payment_provider_modena").sudo().copy({
            "company_id": cls.env.company.id,
            "modena_client_id": "client", "modena_client_secret": "secret",
            "is_published": True, "journal_id": cls.company_data["default_journal_bank"].id,
        })
        cls.slice = cls.provider.with_context(active_test=False).payment_method_ids.filtered(
            lambda m: m.code == "modena_slice"
        )
        cls.slice.active = True
        cls.product = cls.create_product("Sofa", cls.categ_basic, 100)
        online = cls.env["pos.payment.method"].create({
            "name": "Modena", "type": "online", "online_payment_provider_ids": [(6, 0, cls.provider.ids)],
        })
        cls.config.payment_method_ids |= online
        cls.stock_location = cls.config.picking_type_id.default_location_src_id
        cls.env["stock.quant"]._update_available_quantity(cls.product, cls.stock_location, 5)

    def setUp(self):
        super().setUp()
        self.open_new_session()
        order_data = self.create_ui_order_data([(self.product, 2)], {"state": "draft"}, payments=[])
        order_id = self.env["pos.order"].sync_from_ui([order_data])["pos.order"][0]["id"]
        self.order = self.env["pos.order"].browse(order_id)
        self.order.next_online_payment_amount = self.order.amount_total

    def _create_tx(self, state="draft"):
        return self.env["payment.transaction"].create({
            "provider_id": self.provider.id,
            "payment_method_id": self.slice.id,
            "amount": self.order.amount_total,
            "currency_id": self.order.currency_id.id,
            "partner_id": self.env.company.partner_id.id,
            "reference": f"POS-{self.order.id}-{state}",
            "pos_order_id": self.order.id,
            "state": state,
        })

    def test_paid_order_notifies_the_till(self):
        tx = self._create_tx("done")
        with patch.object(type(self.config), "_notify") as notify:
            tx.with_context(payment_safe_write=True)._post_process()
        self.assertEqual(self.order.state, "paid")
        notify.assert_any_call("MODENA_POS_PAYMENT", {
            "id": self.order.id, "name": self.order.tracking_number or self.order.name, "status": "paid",
        })

    def test_rejected_application_notifies_the_till(self):
        tx = self._create_tx()
        with patch.object(type(self.config), "_notify") as notify:
            tx.with_context(payment_safe_write=True)._apply_updates({"status": "REJECTED"})
        self.assertEqual(tx.state, "cancel")
        self.assertEqual(notify.call_args[0][1]["status"], "rejected")

    def test_payment_after_closing_is_kept_for_accounting(self):
        tx = self._create_tx("done")
        self.pos_session.sudo().state = "closed"
        tx.with_context(payment_safe_write=True)._post_process()
        self.assertEqual(self.order.state, "draft")
        self.assertFalse(self.order.payment_ids)
        self.assertTrue(tx.payment_id)
        self.assertEqual(tx.payment_id.activity_ids.summary, "Online payment after POS closing")
        self.assertIn("after the POS session", self.order.message_ids[0].body)

    def test_pay_page_shows_order_lines(self):
        response = self.url_open(f"/pos/pay/{self.order.id}?access_token={self.order.access_token}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sofa", response.text)
        self.assertIn(self.env.company.name, response.text)

    def _free_qty(self):
        return self.product.with_context(location=self.stock_location.id).free_qty

    def test_park_reserves_and_payment_releases(self):
        self.order.action_modena_park(30)
        reservation = self.order.modena_reservation_id
        self.assertEqual(reservation.state, "assigned")
        self.assertEqual(self._free_qty(), 3)
        self.assertFalse(self.order.picking_ids, "the reservation must not look like the delivery")

        tx = self._create_tx("done")
        tx.with_context(payment_safe_write=True)._post_process()
        self.assertEqual(self.order.state, "paid")
        self.assertEqual(reservation.state, "cancel")
        self.assertTrue(self.order.picking_ids)

    def test_expired_order_is_cancelled_and_released(self):
        self.order.action_modena_park(30)
        self.order.modena_parked_until = fields.Datetime.now() - timedelta(minutes=1)
        with patch.object(type(self.config), "_notify") as notify:
            self.env["pos.order"]._cron_modena_expire_parked()
        self.assertEqual(self.order.state, "cancel")
        self.assertEqual(self.order.modena_reservation_id.state, "cancel")
        self.assertEqual(self._free_qty(), 5)
        self.assertEqual(notify.call_args[0][1]["status"], "expired")

    def test_started_payment_is_not_expired(self):
        self.order.action_modena_park(30)
        self.order.modena_parked_until = fields.Datetime.now() - timedelta(minutes=1)
        self._create_tx("pending")
        self.env["pos.order"]._cron_modena_expire_parked()
        self.assertEqual(self.order.state, "draft")
        self.assertEqual(self.order.modena_reservation_id.state, "assigned")

    def test_cancelling_parked_order_releases_stock(self):
        self.order.action_modena_park(30)
        self.order.with_context(active_ids=self.order.ids).action_pos_order_cancel()
        self.assertEqual(self._free_qty(), 5)

    def test_pay_page_refuses_expired_slip(self):
        self.order.action_modena_park(30)
        self.order.modena_parked_until = fields.Datetime.now() - timedelta(minutes=1)
        url = f"/pos/pay/{self.order.id}?access_token={self.order.access_token}"
        self.assertIn("time to pay this order has ended", self.url_open(url).text)

        self.env["pos.order"]._cron_modena_expire_parked()
        self.assertIn("time to pay this order has ended", self.url_open(url).text)
