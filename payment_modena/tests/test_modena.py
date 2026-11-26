from unittest.mock import Mock, patch

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.payment_modena.controllers.main import ModenaController, modena_signature
from odoo.addons.payment_modena.models import payment_provider
from odoo.addons.payment_modena.tests.common import PROVIDER_PATH, ModenaCommon, mock_response


@tagged("post_install", "-at_install")
class TestModena(ModenaCommon, PaymentHttpCommon):

    def test_financing_payload_uses_order_lines(self):
        order = self._create_order()
        tx = self._create_order_tx(order)
        payload = tx._modena_prepare_financing_payload()

        self.assertEqual(payload["orderId"], tx.reference)
        self.assertEqual(payload["totalAmount"], 248)
        self.assertEqual(payload["totalNetAmount"], 200)
        self.assertEqual(payload["totalTaxAmount"], 48)
        self.assertEqual(payload["orderItems"], [{
            "description": "Sofa", "amount": 124, "currency": "EUR", "quantity": 2,
            "netAmount": 100, "taxAmount": 24, "taxRate": 24,
        }])
        self.assertEqual(payload["customer"]["phoneNumber"], "+3212345678")
        self.assertEqual(payload["customer"]["firstName"], "Norbert")
        self.assertEqual(payload["country"], "EE")
        self.assertTrue(payload["callbackUrl"].endswith(ModenaController._webhook_url))
        self.assertNotIn("maturityInMonths", payload)

    def test_financing_payload_falls_back_to_one_line(self):
        order = self._create_order(qty=1.5)
        tx = self._create_order_tx(order)
        items = tx._modena_prepare_financing_payload()["orderItems"]
        self.assertEqual(items, [{
            "description": tx.reference, "amount": 186, "currency": "EUR", "quantity": 1
        }])

        partial_tx = self._create_transaction("redirect", reference="partial", amount=10)
        self.assertEqual(partial_tx._modena_financing_items()[0]["amount"], 10)

    def test_term_is_sent_when_set(self):
        self.slice.modena_maturity_months = 12
        tx = self._create_transaction("redirect")
        self.assertEqual(tx._modena_prepare_financing_payload()["maturityInMonths"], 12)

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_missing_phone_sets_error_without_request(self):
        self.partner.phone = False
        tx = self._create_transaction("redirect")
        with patch(f"{PROVIDER_PATH}.requests.request") as request_mock:
            tx._get_processing_values()
        request_mock.assert_not_called()
        self.assertEqual(tx.state, "error")

    def test_order_creation_reads_redirect(self):
        tx = self._create_transaction("redirect")
        onboarding = f"https://onboarding-dev.modena.ee/{self.application_id}"
        response = mock_response(
            302, {"id": self.application_id, "onboardingUrl": onboarding}, {"Location": onboarding}
        )
        with patch(f"{PROVIDER_PATH}.requests.request", return_value=response) as request_mock:
            processing_values = tx._get_processing_values()

        args, kwargs = request_mock.call_args
        self.assertEqual(
            args[1], "https://api-dev.modena.ee/modena/api/merchant/slice-payment-order"
        )
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer token")
        self.assertEqual(tx.provider_reference, self.application_id)
        form = self._extract_values_from_html_form(processing_values["redirect_form_html"])
        self.assertEqual(form["action"], onboarding)
        self.assertEqual(form["method"], "get")

    def test_live_mode_uses_live_api(self):
        self.provider.is_live = True
        tx = self._create_transaction("redirect")
        response = mock_response(302, {"id": self.application_id}, {"Location": "https://x.ee/"})
        with patch(f"{PROVIDER_PATH}.requests.request", return_value=response) as request_mock:
            tx._get_processing_values()
        self.assertTrue(request_mock.call_args[0][1].startswith("https://api.modena.ee/"))

    @mute_logger("odoo.addons.payment.models.payment_transaction", PROVIDER_PATH)
    def test_api_error_is_readable(self):
        tx = self._create_transaction("redirect")
        response = mock_response(400, {
            "detail": "Request body has 1 invalid field",
            "errors": [{"field": "totalAmount", "message": "is required"}],
        })
        with patch(f"{PROVIDER_PATH}.requests.request", return_value=response):
            tx._get_processing_values()
        self.assertEqual(tx.state, "error")
        self.assertIn("totalAmount: is required", tx.state_message)

    def test_token_is_cached_per_scope(self):
        provider = self.provider
        token = mock_response(200, {"access_token": "abc", "expires_in": 299})
        self.token_patcher.stop()
        payment_provider._token_cache.clear()
        with patch(f"{PROVIDER_PATH}.requests.post", return_value=token) as post_mock:
            self.assertEqual(provider._modena_get_access_token("slicepayment"), "abc")
            provider._modena_get_access_token("slicepayment")
            provider._modena_get_access_token("directpayment")
        self.assertEqual(post_mock.call_count, 2)
        self.assertEqual(post_mock.call_args[1]["data"]["scope"], "directpayment")
        self.assertEqual(post_mock.call_args[0][0], "https://login-dev.modena.ee/oauth2/token")

    def test_direct_payload(self):
        bank = self.env["payment.method"].create({
            "name": "Test bank", "code": "modena_direct_testee22", "provider_id": self.provider.id,
            "active": True, "image": self.slice.image,
        })
        tx = self._create_transaction("redirect", payment_method_id=bank.id)
        payload = tx._modena_prepare_direct_payload()
        self.assertEqual(payload["selectedOption"], "TESTEE22")
        self.assertEqual(payload["language"], "EN")
        self.assertEqual(set(payload["orderItems"][0]), {"description", "amount", "currency", "quantity"})
        self.assertEqual(tx._modena_scope(), "directpayment")

    def test_operating_lease_payload(self):
        self.product.modena_asset_catalog_entry_id = "a4d0c5d4-1d6b-4b6c-9b0a-1f7f3d1e2c3b"
        self.product.modena_buyback_percentage = 10
        order = self._create_order()
        tx = self._create_order_tx(order, method=self.lease)
        payload = tx._modena_prepare_operating_lease_payload()
        self.assertEqual(payload["maturityInMonths"], 36)
        self.assertEqual(len(payload["orderItems"]), 2)
        self.assertEqual(payload["orderItems"][0]["netPriceAmount"], 100)
        self.assertEqual(payload["orderItems"][0]["vatAmount"], 24)
        self.assertEqual(payload["orderItems"][0]["vatPercentage"], 24)
        self.assertNotEqual(
            payload["orderItems"][0]["assetIdentifier"], payload["orderItems"][1]["assetIdentifier"]
        )
        self.assertNotIn("totalAmount", payload)

        self.product.modena_asset_catalog_entry_id = False
        with self.assertRaises(ValidationError):
            tx._modena_prepare_operating_lease_payload()

    def test_status_mapping(self):
        for status, state in (
            ("OUTSTANDING", "pending"),
            ("IN_MANUAL_REVIEW", "pending"),
            ("SUCCESS", "done"),
            ("REJECTED", "cancel"),
            ("EXPIRED", "cancel"),
            ("FAILED", "error"),
        ):
            tx = self._create_transaction("redirect", reference=f"tx-{status}")
            tx.with_context(payment_safe_write=True)._apply_updates({"status": status})
            self.assertEqual(tx.state, state, status)

    def test_success_after_cancel(self):
        tx = self._create_transaction("redirect", state="cancel")
        tx.with_context(payment_safe_write=True)._apply_updates({"status": "SUCCESS"})
        self.assertEqual(tx.state, "done")

    def test_signature_matches_documentation_example(self):
        self.assertEqual(
            modena_signature(
                "68de6cbe-395d-49d0-85a7-ed5995794aef",
                "caae8a5e-619a-4010-b7e5-fd8081438201",
                "111222333",
            ),
            "c17962392545337ad71755be23254090bebbe96fcbd9c348c91d2fe35696d1c4",
        )

    def _post_webhook(self, data, status="SUCCESS", **kwargs):
        url = self._build_url(ModenaController._webhook_url)
        with patch(
            f"{PROVIDER_PATH}.PaymentProvider._modena_send_request", return_value={"status": status}, **kwargs
        ) as request_mock:
            response = self._make_http_post_request(url, data=data)
        return response, request_mock

    @mute_logger("odoo.addons.payment_modena.controllers.main")
    def test_webhook_confirms_transaction(self):
        self._disable_process_patcher()
        tx = self._create_transaction("redirect", provider_reference=self.application_id)
        response, request_mock = self._post_webhook({**self.payment_data, "action": "payment.confirmed"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.application_id, request_mock.call_args[0][1])
        self._run_processing()
        self.assertEqual(tx.state, "done")

    @mute_logger("odoo.addons.payment_modena.controllers.main")
    def test_webhook_ignores_foreign_application(self):
        self._create_transaction("redirect", provider_reference="other-application")
        _response, request_mock = self._post_webhook(self.payment_data)
        request_mock.assert_not_called()

    @mute_logger("odoo.addons.payment_modena.controllers.main")
    def test_webhook_rejects_bad_signature(self):
        self._create_transaction("redirect", provider_reference=self.application_id)
        url = self._build_url(ModenaController._webhook_url)
        with patch(f"{PROVIDER_PATH}.PaymentProvider._modena_send_request") as request_mock:
            self.opener.post(url, data=self.payment_data, headers={"X-Modena-Signature": "bad"}, timeout=10)
        request_mock.assert_not_called()

    @mute_logger("odoo.addons.payment_modena.controllers.main")
    def test_webhook_asks_retry_when_modena_is_down(self):
        self._create_transaction("redirect", provider_reference=self.application_id)
        response, _mock = self._post_webhook(self.payment_data, side_effect=ValidationError("down"))
        self.assertEqual(response.status_code, 503)

    @mute_logger("odoo.addons.payment_modena.controllers.main")
    def test_return_redirects_to_status_page(self):
        self._create_transaction("redirect", provider_reference=self.application_id)
        url = self._build_url(ModenaController._cancel_url)
        with patch(
            f"{PROVIDER_PATH}.PaymentProvider._modena_send_request", return_value={"status": "OUTSTANDING"}
        ):
            response = self._make_http_post_request(url, data=self.payment_data)
        self.assertTrue(response.url.endswith("/payment/status"))

    @mute_logger("odoo.addons.payment_modena.controllers.main")
    def test_cancel_marks_unfinished_application_cancelled(self):
        self._disable_process_patcher()
        tx = self._create_transaction("redirect", provider_reference=self.application_id)
        url = self._build_url(ModenaController._cancel_url)
        with patch(
            f"{PROVIDER_PATH}.PaymentProvider._modena_send_request", return_value={"status": "OUTSTANDING"}
        ):
            self._make_http_post_request(url, data=self.payment_data)
        self._run_processing()
        self.assertEqual(tx.state, "cancel")

        tx.with_context(payment_safe_write=True)._apply_updates({"status": "SUCCESS"})
        self.assertEqual(tx.state, "done")

    def test_late_approval_flags_the_order(self):
        order = self._create_order()
        tx = self._create_order_tx(order, state="cancel")
        tx.with_context(payment_safe_write=True)._apply_updates({"status": "SUCCESS"})
        self.assertEqual(tx.state, "done")
        self.assertEqual(order.activity_ids.summary, "Modena payment approved late")

    def test_cron_checks_only_pending_modena_transactions(self):
        self.env["payment.transaction"].search([("provider_code", "=", "modena")]).with_context(
            payment_safe_write=True
        ).state = "done"
        pending = self._create_transaction("redirect", reference="pending", state="pending", provider_reference="a")
        self._create_transaction("redirect", reference="done", state="done", provider_reference="b")
        self._create_transaction("redirect", reference="no-ref", state="pending")
        with patch(
            f"{PROVIDER_PATH}.PaymentProvider._modena_send_request", return_value={"status": "REJECTED"}
        ) as request_mock:
            self.env["payment.transaction"]._cron_modena_check_pending()
        self.assertEqual(request_mock.call_count, 1)
        self.assertIn("/applications/a/status", request_mock.call_args[0][1])
        self.assertEqual(pending.payment_data_ids.mapped("payload")[-1]["status"], "REJECTED")

    def test_bank_sync(self):
        for method in self.env["payment.method"].with_context(active_test=False).search([
            ("code", "=like", "modena_direct_%")
        ]):
            method.code = f"old_{method.id}"
        old = self.env["payment.method"].create({
            "name": "Gone", "code": "modena_direct_gonebank", "provider_id": self.provider.id,
            "active": True, "image": self.slice.image,
        })
        banks = {
            "EE": {"supportedCurrencies": ["EUR"], "paymentMethods": [
                {"code": "LHVBEE22", "name": "AS LHV Pank", "order": 3, "buttonUrl": "https://cdn/lhv.png"},
                {"code": "REVOLT21", "name": "Revolut", "order": 7, "buttonUrl": "https://cdn/rev.png"},
            ]},
            "LV": {"supportedCurrencies": ["EUR"], "paymentMethods": [
                {"code": "REVOLT21", "name": "Revolut", "order": 5, "buttonUrl": "https://cdn/rev.png"},
            ]},
        }
        with patch(f"{PROVIDER_PATH}.PaymentProvider._modena_send_request", return_value=banks), \
                patch(f"{PROVIDER_PATH}.requests.get", side_effect=[
                    payment_provider.requests.exceptions.ConnectionError,
                    Mock(content=self.slice.image.content, raise_for_status=Mock()),
                ]):
            self.provider.action_modena_sync_banks()

        methods = self.env["payment.method"].with_context(active_test=False).search([
            ("provider_id", "=", self.provider.id), ("code", "=like", "modena_direct_%"),
        ])
        revolut = methods.filtered(lambda m: m.code == "modena_direct_revolt21")
        self.assertEqual(set(revolut.supported_country_ids.mapped("code")), {"EE", "LV"})
        self.assertFalse(revolut.active)
        lhv = methods.filtered(lambda m: m.code == "modena_direct_lhvbee22")
        self.assertEqual(lhv.image.content, self.slice.image.content)
        self.assertEqual(revolut.image.content, self.slice.image.content)
        self.assertFalse(old.active)

    def test_financing_needs_customer_contact(self):
        bank = self.env["payment.method"].create({
            "name": "Test bank", "code": "modena_direct_testee22", "provider_id": self.provider.id,
            "active": True, "image": self.slice.image,
        })
        self.partner.country_id = self.env.ref("base.ee")
        codes = self.provider._find_available_payment_methods(self.partner.id).mapped("code")
        self.assertIn("modena_slice", codes)

        self.partner.phone = False
        codes = self.provider._find_available_payment_methods(self.partner.id).mapped("code")
        self.assertNotIn("modena_slice", codes)
        self.assertIn(bank.code, codes)

    def test_partner_without_country_sees_local_banks(self):
        self.env.company.country_id = self.env.ref("base.ee")
        for code, country in (("modena_direct_eetest", "base.ee"), ("modena_direct_lvtest", "base.lv")):
            self.env["payment.method"].create({
                "name": code, "code": code, "provider_id": self.provider.id, "active": True,
                "image": self.slice.image,
                "supported_country_ids": [Command.set(self.env.ref(country).ids)],
            })
        self.partner.country_id = False
        codes = self.provider._find_available_payment_methods(self.partner.id).mapped("code")
        self.assertIn("modena_direct_eetest", codes)
        self.assertNotIn("modena_direct_lvtest", codes)

    def test_amount_limits(self):
        self.slice.write({"modena_min_amount": 50, "modena_max_amount": 1000})
        self.assertFalse(self.slice._modena_is_available_for(49.99, self.currency))
        self.assertTrue(self.slice._modena_is_available_for(50, self.currency))
        self.assertFalse(self.slice._modena_is_available_for(1000.01, self.currency))

    def test_unavailable_methods_are_hidden(self):
        self.slice.modena_max_amount = 100
        order = self._create_order()
        methods = self.provider.payment_method_ids._modena_filter_available(248, self.currency, order)
        codes = methods.mapped("code")
        self.assertNotIn("modena_slice", codes)
        self.assertNotIn("modena_operating_lease", codes)
        self.assertIn("modena_credit", codes)

        self.product.modena_asset_catalog_entry_id = "catalog-id"
        methods = self.provider.payment_method_ids._modena_filter_available(248, self.currency, order)
        self.assertIn("modena_operating_lease", methods.mapped("code"))
