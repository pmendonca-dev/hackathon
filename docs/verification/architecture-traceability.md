# AVAL architecture traceability

Delivery status: pre-gate

This is a verification map, not final-delivery evidence. It identifies the
runtime boundary and regression evidence that a final gate must run on the
candidate commit. It does not assert that the final delivery gate has passed.

| Requirement | Route or service | Regression evidence |
| --- | --- | --- |
| RFC 9421 | `Rfc9421Verifier` protects the UCP checkout, `POST /agentic_commerce/delegate_payment`, `POST /payment-captures`, revocation, audit, and receipt reads. `RawBodyMiddleware` preserves the signed bytes. | `tests/integration/api/test_live_payment_runtime.py::test_operational_posts_require_rfc9421_authentication`; `tests/integration/e2e/test_task_12_live_runtime.py::test_impostor_invalid_signature_and_raw_body_tampering_are_rejected` |
| AP2 v0.2 | `CheckoutService`, `ClosedCheckoutMandateVerifier`, and `MerchantAuthorizationVerifier` bind the persisted checkout to the AP2 mandate before capture. | `tests/integration/api/test_ucp_runtime.py::test_mounted_completion_rejects_invalid_ap2_audience_and_nonce`; `tests/integration/api/test_live_payment_runtime.py::test_invalid_ap2_chain_creates_no_reservation_settlement_receipt_or_audit` |
| ACP delegated payment / vault token | `POST /agentic_commerce/delegate_payment` calls `DurableDelegationService` and `VaultService`; `OpaqueTestCredentialTokenizer` emits an opaque scoped token rather than card data. | `tests/integration/api/test_live_payment_runtime.py::test_delegate_and_capture_accept_only_the_authenticated_agent_role`; `tests/integration/api/test_delegate_payment.py::test_delegate_payment_uses_fresh_authorized_state_for_each_token` |
| Live revocation | `POST /mandates/{mandate_id}/revocations` calls `AuthorizationCore.submit_signed_revocation_idempotent` under the durable mandate lock. | `tests/integration/api/test_live_payment_runtime.py::test_signed_revocation_is_authenticated_idempotent_and_audited`; `tests/integration/application/test_revocation_commit_race.py::test_revocation_after_commit_does_not_cancel_inflight_settlement_but_blocks_next_attempt` |
| Capture / MockCardPSP / receipts | `POST /payment-captures` calls `PaymentRuntime`, which obtains the Core commit before `MockCardPSP`; `ReceiptService` emits AP2 receipts only after approved settlement. | `tests/integration/api/test_live_payment_runtime.py::test_runtime_issues_receipts_only_after_settlement_and_mounts_audit`; `tests/integration/application/test_receipt_ordering.py::test_receipts_are_signed_and_issued_only_after_settlement` |
| Audit / dispute | `GET /audit/mandates/{mandate_id}` and `/audit/mandates/{mandate_id}/dispute` use `DisputeService` and the append-only audit ledger. | `tests/integration/application/test_audit_timeline.py::test_audit_timeline_is_immutable_legible_and_explains_post_commit_revocation`; `tests/integration/api/test_live_payment_runtime.py::test_valid_purchase_exposes_receipts_audit_and_dispute_without_secrets` |
| Browser BFF / session / CSRF | `/ui-api/v1/session/login`, `/ui-api/v1/session/logout`, and `/ui-api/v1/workspace` use `UiSessionService`, `UiProjectionService`, HttpOnly sessions, and `X-AVAL-CSRF` for mutations. | `tests/integration/api/test_ui_session_api.py`; `tests/integration/api/test_ui_operator_revocation_api.py::test_operator_revocation_requires_session_csrf_and_idempotency_and_is_server_signed` |
| No browser secrets | `UiProjectionService` redacts payment authority material; `mount_browser_build` serves the static build without synthesizing runtime values. | `tests/integration/e2e/test_browser_safe_bff.py::test_browser_projection_redacts_pan_token_proof_and_raw_jws`; `tests/integration/api/test_browser_same_origin_delivery.py::test_same_origin_delivery_never_synthesizes_runtime_secrets_into_static_responses` |
| x402 — disabled | No x402 route, adapter, chain client, or facilitator is mounted in this delivery. The card path remains the only settlement rail exercised by this gate. | `tests/unit/test_protocol_validation_document.py`; `scripts/demo_smoke.py` reports the intentional exclusion while exercising the non-x402 runtime path. |

## Authority boundary

`AuthorizationCore` remains the only authority for mandate status, merchant and
checkout scope, budget, expiry, revocation, reservation commit, and proof
issuance. Protocol and browser components are edge representations of that
state; none owns a second policy, ledger, or spending decision.

## Final-gate rule

The entries above are evidence locations. A release candidate is not complete
until the clean-environment rehearsal is run against its exact commit, including
the browser inspection and the legacy-database repair check.
