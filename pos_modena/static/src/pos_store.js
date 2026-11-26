import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this.data.connectWebSocket("MODENA_POS_PAYMENT", (payload) =>
            this.onModenaPayment(payload)
        );
    },

    async onModenaPayment({ id, name, status }) {
        if (status === "paid") {
            // pos_online_payment reloads the order on its own notification; fetch it in case ours is first.
            const [order] = await this.data.loadServerOrders([["id", "=", id]]);
            this.notification.add(_t("Order %s has been paid.", name), {
                type: "success",
                sticky: true,
                buttons: order
                    ? [{
                          name: _t("Print receipt"),
                          primary: true,
                          onClick: () => this.ticketPrinter.printOrderReceipt({ order }),
                      }]
                    : [],
            });
            return;
        }
        if (status === "expired") {
            await this.data.loadServerOrders([["id", "=", id]]);
            this.notification.add(
                _t("Order %s was not paid in time. It was cancelled and its products released.", name),
                { type: "warning", sticky: true }
            );
            return;
        }
        const order = this.models["pos.order"].find((o) => o.id === id);
        this.notification.add(
            _t("The payment for order %s failed. Open it to take another payment.", name),
            {
                type: "warning",
                sticky: true,
                buttons: order
                    ? [{
                          name: _t("Open order"),
                          onClick: () => {
                              this.setOrder(order);
                              this.navigateToOrderScreen(order);
                          },
                      }]
                    : [],
            }
        );
    },
});
