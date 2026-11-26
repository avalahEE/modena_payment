from . import controllers, models


def post_init_hook(env):
    # Tills only refetch records whose write_date changed, so touch the existing methods
    # or cached tills keep the new field empty.
    methods = env["pos.payment.method"].search([])
    methods.write({"modena_payment_slip": True, "modena_slip_minutes": 30})
