from __future__ import annotations

import hashlib
import hmac
import json
import unittest

from src.platform.stripe_client import (
    StripeConfigurationError,
    StripeWebhookReceiver,
    StripeWebhookSignatureError,
    build_checkout_session_params,
    create_checkout_session,
    load_tier_price_ids,
    receive_webhook,
)


def _signature_header(payload: bytes, secret: str, timestamp: int) -> str:
    signed_payload = f"{timestamp}.".encode("utf-8") + payload
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


class _FakeStripeSession:
    calls: list[dict] = []

    @classmethod
    def create(cls, **params: object) -> dict:
        cls.calls.append(params)
        return {"id": "cs_test_123", "url": "https://checkout.stripe.test/cs_123"}


class _FakeCheckout:
    Session = _FakeStripeSession


class _FakeStripe:
    api_key = ""
    checkout = _FakeCheckout()


class TestStripeClient(unittest.TestCase):
    def setUp(self) -> None:
        _FakeStripe.api_key = ""
        _FakeStripeSession.calls = []

    def test_load_tier_price_ids_from_json_and_per_tier_env(self) -> None:
        mapping = load_tier_price_ids(
            {
                "MEDIA_ARK_STRIPE_PRICE_IDS": '{"starter":"price_starter"}',
                "MEDIA_ARK_STRIPE_PRICE_PRO": "price_pro",
                "MEDIA_ARK_STRIPE_PRICE_ID_TEAM": "price_team",
                "MEDIA_ARK_STRIPE_ENTERPRISE_PRICE_ID": "price_enterprise",
            }
        )

        self.assertEqual(mapping["starter"], "price_starter")
        self.assertEqual(mapping["pro"], "price_pro")
        self.assertEqual(mapping["team"], "price_team")
        self.assertEqual(mapping["enterprise"], "price_enterprise")

    def test_build_checkout_session_params_maps_tier_to_price(self) -> None:
        params = build_checkout_session_params(
            "Pro",
            "https://example.test/success",
            "https://example.test/cancel",
            price_ids={"pro": "price_pro"},
            mode="payment",
            quantity=2,
            metadata={"account_id": "acct_123"},
            client_reference_id="user_123",
            customer_email="buyer@example.test",
            allow_promotion_codes=True,
            automatic_tax=True,
        )

        self.assertEqual(params["mode"], "payment")
        self.assertEqual(
            params["line_items"], [{"price": "price_pro", "quantity": 2}]
        )
        self.assertEqual(params["metadata"]["tier"], "pro")
        self.assertEqual(params["metadata"]["account_id"], "acct_123")
        self.assertEqual(params["client_reference_id"], "user_123")
        self.assertEqual(params["customer_email"], "buyer@example.test")
        self.assertEqual(params["allow_promotion_codes"], True)
        self.assertEqual(params["automatic_tax"], {"enabled": True})

    def test_create_checkout_session_returns_redirect_url(self) -> None:
        url = create_checkout_session(
            "pro",
            "https://example.test/success",
            "https://example.test/cancel",
            price_ids={"pro": "price_pro"},
            stripe_module=_FakeStripe,
            api_key="sk_test_123",
            mode="subscription",
        )

        self.assertEqual(url, "https://checkout.stripe.test/cs_123")
        self.assertEqual(_FakeStripe.api_key, "sk_test_123")
        self.assertEqual(len(_FakeStripeSession.calls), 1)
        self.assertEqual(
            _FakeStripeSession.calls[0]["line_items"],
            [{"price": "price_pro", "quantity": 1}],
        )

    def test_unknown_tier_is_configuration_error(self) -> None:
        with self.assertRaises(StripeConfigurationError):
            build_checkout_session_params(
                "enterprise",
                "https://example.test/success",
                "https://example.test/cancel",
                price_ids={"pro": "price_pro"},
            )

    def test_receive_webhook_validates_signature_and_returns_event(self) -> None:
        secret = "whsec_test"
        timestamp = 1_700_000_000
        payload = json.dumps(
            {
                "id": "evt_123",
                "type": "checkout.session.completed",
                "data": {"object": {"id": "cs_123"}},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        event = receive_webhook(
            payload,
            _signature_header(payload, secret, timestamp),
            secret,
            now=timestamp,
        )

        self.assertEqual(event["id"], "evt_123")
        self.assertEqual(event["type"], "checkout.session.completed")

    def test_receive_webhook_rejects_invalid_signature(self) -> None:
        secret = "whsec_test"
        timestamp = 1_700_000_000
        payload = b'{"id":"evt_123","type":"checkout.session.completed"}'
        header = _signature_header(payload, secret, timestamp)

        with self.assertRaises(StripeWebhookSignatureError):
            receive_webhook(
                b'{"id":"evt_123","type":"payment_intent.succeeded"}',
                header,
                secret,
                now=timestamp,
            )

    def test_receiver_dispatches_after_signature_validation(self) -> None:
        secret = "whsec_test"
        timestamp = 1_700_000_000
        payload = b'{"id":"evt_123","type":"checkout.session.completed"}'
        received: list[str] = []
        receiver = StripeWebhookReceiver(
            endpoint_secret=secret,
            clock=lambda: timestamp,
            handlers={
                "checkout.session.completed": lambda event: received.append(
                    str(event["id"])
                )
            },
        )

        event = receiver.receive(payload, _signature_header(payload, secret, timestamp))

        self.assertEqual(event["id"], "evt_123")
        self.assertEqual(received, ["evt_123"])


if __name__ == "__main__":
    unittest.main()
