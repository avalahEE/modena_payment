API_URL = {False: "https://api-dev.modena.ee", True: "https://api.modena.ee"}
TOKEN_URL = {
    False: "https://login-dev.modena.ee/oauth2/token",
    True: "https://login.modena.ee/oauth2/token",
}

# payment method code: (endpoint, scope)
FINANCING_PRODUCTS = {
    "modena_slice": ("slice-payment-order", "slicepayment"),
    "modena_credit": ("credit-payment-order", "creditpayment"),
    "modena_click_try": ("click-and-try-payment-order", "clickandtrypayment"),
    "modena_business_leasing": ("business-leasing-payment-order", "businessleasing"),
    "modena_business_factoring": ("business-factoring-payment-order", "businessfactoring"),
    "modena_operating_lease": ("operating-lease-payment-order", "operatinglease"),
}
DIRECT_PREFIX = "modena_direct_"
DIRECT_SCOPE = "directpayment"

FINANCING_COUNTRIES = ("EE", "LV")
DIRECT_COUNTRIES = ("EE", "LV", "LT")
DIRECT_LANGUAGES = ("ET", "EN", "LV", "LT", "RU")
OPERATING_LEASE_TERMS = (12, 24, 36)

SUPPORTED_CURRENCIES = ("EUR",)
DEFAULT_PAYMENT_METHOD_CODES = {"modena_slice", "modena_credit"}

STATUS_MAPPING = {
    "pending": ("OUTSTANDING", "IN_MANUAL_REVIEW"),
    "done": ("SUCCESS",),
    "cancel": ("REJECTED", "EXPIRED"),
    "error": ("FAILED",),
}
