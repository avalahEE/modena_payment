import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { generateQRCodeDataUrl } from "@point_of_sale/utils";
import { QRPopup } from "@point_of_sale/app/components/popups/qr_code_popup/qr_code_popup";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";

patch(QRPopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.pos = usePos();
    },

    get modenaLine() {
        const order = this.pos.getOrder();
        if (!order || order.onlinePaymentData?.qrCode !== this.props.qrCode) {
            return null;
        }
        return order.payment_ids.find(
            (l) =>
                l.payment_method_id.type === "online" &&
                l.payment_method_id.modena_payment_slip &&
                l.getPaymentStatus() === "waiting"
        );
    },

    async printModenaSlip() {
        const line = this.modenaLine;
        const order = this.pos.getOrder();
        const config = this.pos.config;
        const url = `${config._base_url}/pos/pay/${order.id}?access_token=${order.access_token}`;
        const until = await this.pos.data.call("pos.order", "action_modena_park", [
            order.id,
            line.payment_method_id.modena_slip_minutes,
        ]);
        const printer = this.pos.ticketPrinter;
        const iframe = await printer.generateIframe("pos_modena.payment_slip", {
            company: config.company_id.raw,
            config: config.raw,
            image: { logo: config.receiptLogoUrl },
            extra_data: {
                order_name: order.tracking_number || order.name,
                date: new Date().toLocaleString(),
                lines: order.lines.map((l) => ({
                    name: l.getFullProductName(),
                    qty: l.qty,
                    price: l.currencyDisplayPrice,
                })),
                amount: this.props.amount,
                valid_until: luxon.DateTime.fromSQL(until, { zone: "utc" }).toLocal().toFormat("HH:mm"),
                qr_code: generateQRCodeDataUrl(url, { width: 250, height: 250 }),
            },
        });
        await printer.printWithFallback({ iframe });

        // Park the order: keep it on the server so the payment can still land on it.
        order.modenaParked = true;
        line.onlinePaymentResolver?.(false);
        this.props.close();
        const next = this.pos.addNewOrder();
        this.pos.navigate("ProductScreen", { orderUuid: next.uuid });
        this.pos.notification.add(
            _t("Order %s is waiting for the payment.", order.tracking_number || order.name),
            { type: "info" }
        );
    },
});

patch(OrderPaymentValidation.prototype, {
    cancelOnlinePayment(order) {
        if (order.modenaParked) {
            return;
        }
        return super.cancelOnlinePayment(...arguments);
    },
});
