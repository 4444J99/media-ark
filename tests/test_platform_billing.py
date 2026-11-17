from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.platform.billing import (
    BillingConflictError,
    BillingError,
    BillingNotFoundError,
    BillingStore,
    SubscriptionStore,
    TIER_QUOTAS,
    apply_stripe_webhook,
    stripe_webhook_update,
)


class TestPlatformBilling(unittest.TestCase):
    def test_subscription_crud_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BillingStore(Path(tmpdir) / "billing.db")

            created = store.create(
                42,
                tier="free",
                stripe_customer_id="cus_free",
                renewal="2026-07-01T00:00:00+00:00",
                auto_renew=False,
            )
            self.assertEqual(created.user_id, 42)
            self.assertEqual(created.tier, "free")
            self.assertEqual(created.quota, TIER_QUOTAS["free"])
            self.assertFalse(created.auto_renew)
            self.assertEqual(store.get_subscription(42), created)
            self.assertEqual(store.get_by_stripe_customer_id("cus_free"), created)
            self.assertEqual(store.list_subscriptions(), [created])

            updated = store.update(
                42,
                tier="pro",
                stripe_customer_id="cus_pro",
                renewal="2026-08-01T00:00:00+00:00",
                auto_renew=True,
            )
            self.assertEqual(updated.tier, "pro")
            self.assertEqual(updated.quota, TIER_QUOTAS["pro"])
            self.assertEqual(updated.stripe_customer_id, "cus_pro")
            self.assertTrue(updated.auto_renew)

            custom_quota = store.update(42, quota=12_345)
            self.assertEqual(custom_quota.quota, 12_345)

            self.assertTrue(store.delete(42))
            self.assertIsNone(store.get(42))
            self.assertFalse(store.delete(42))

    def test_subscription_alias_and_tier_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SubscriptionStore(Path(tmpdir) / "billing.db")

            free = store.create_subscription(1)
            pro = store.create_subscription(2, tier="pro")

            self.assertFalse(free.auto_renew)
            self.assertTrue(pro.auto_renew)
            self.assertEqual(store.update_subscription(1, tier="pro").quota, 100_000)
            self.assertTrue(store.delete_subscription(2))

    def test_rejects_invalid_records_and_duplicate_customer_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BillingStore(Path(tmpdir) / "billing.db")

            with self.assertRaises(BillingError):
                store.create(0)
            with self.assertRaises(BillingError):
                store.create(1, tier="enterprise")
            with self.assertRaises(BillingError):
                store.create(1, quota=-1)

            store.create(1, stripe_customer_id="cus_shared")
            with self.assertRaises(BillingConflictError):
                store.create(2, stripe_customer_id="cus_shared")
            with self.assertRaises(BillingNotFoundError):
                store.update(99, tier="pro")

    def test_checkout_webhook_creates_pro_subscription_with_quota(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BillingStore(Path(tmpdir) / "billing.db")
            event = {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "customer": "cus_paid",
                        "client_reference_id": "7",
                        "metadata": {
                            "tier": "pro",
                            "quota": "250000",
                        },
                    }
                },
            }

            updated = apply_stripe_webhook(event, store)

            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.user_id, 7)
            self.assertEqual(updated.tier, "pro")
            self.assertEqual(updated.quota, 250_000)
            self.assertEqual(updated.stripe_customer_id, "cus_paid")
            self.assertTrue(updated.auto_renew)
            self.assertEqual(store.get(7), updated)

    def test_subscription_events_resolve_existing_customer_and_downgrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BillingStore(Path(tmpdir) / "billing.db")
            store.create(9, stripe_customer_id="cus_existing")

            renewal_event = {
                "type": "customer.subscription.updated",
                "data": {
                    "object": {
                        "customer": "cus_existing",
                        "current_period_end": 1_782_864_000,
                        "cancel_at_period_end": False,
                        "items": {
                            "data": [
                                {
                                    "price": {
                                        "metadata": {
                                            "tier": "pro",
                                            "quota": "90000",
                                        }
                                    }
                                }
                            ]
                        },
                    }
                },
            }

            renewed = store.apply_stripe_webhook(renewal_event)

            self.assertIsNotNone(renewed)
            assert renewed is not None
            self.assertEqual(renewed.user_id, 9)
            self.assertEqual(renewed.tier, "pro")
            self.assertEqual(renewed.quota, 90_000)
            self.assertTrue(renewed.auto_renew)
            self.assertEqual(renewed.renewal, "2026-07-01T00:00:00+00:00")

            canceled = store.apply_stripe_webhook(
                {
                    "type": "customer.subscription.deleted",
                    "data": {"object": {"customer": "cus_existing"}},
                }
            )

            self.assertIsNotNone(canceled)
            assert canceled is not None
            self.assertEqual(canceled.tier, "free")
            self.assertEqual(canceled.quota, TIER_QUOTAS["free"])
            self.assertFalse(canceled.auto_renew)

    def test_webhook_parser_ignores_unrelated_events(self) -> None:
        event = {"type": "customer.created", "data": {"object": {"id": "cus_123"}}}

        self.assertIsNone(stripe_webhook_update(event))

    def test_webhook_parser_can_infer_tier_from_price_lookup(self) -> None:
        update = stripe_webhook_update(
            {
                "type": "invoice.payment_succeeded",
                "data": {
                    "object": {
                        "customer_id": "cus_lookup",
                        "subscription_details": {"metadata": {"user_id": "3"}},
                        "lines": {
                            "data": [
                                {
                                    "price": {
                                        "lookup_key": "media-ark-pro-monthly",
                                    }
                                }
                            ]
                        },
                    }
                },
            }
        )

        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update["tier"], "pro")
        self.assertEqual(update["quota"], TIER_QUOTAS["pro"])


if __name__ == "__main__":
    unittest.main()
