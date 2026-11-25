# Financial logic and planted scenarios

The generator (`data_generator/`) produces a fictitious group, **Halcyon Group**: 15 legal entities with 9 functional
currencies, 2021-01 to 2025-12. It uses true double-entry bookkeeping. Each business process posts
balanced journals through one `Ledger.post` call. That call rejects unbalanced entries and postings into
closed periods.

## Business processes

| Process | Module | Accounting |
|---|---|---|
| Order-to-cash | `invoices.py` | Dr 1100 AR / Cr 4000-4100 revenue / Cr 2200 output VAT. Receipts, partial payments, early-payment discounts, credit notes, refunds, write-offs |
| Procure-to-pay | `procurement.py` | Requisition → PO → goods receipt → invoice (Dr expense / inventory / PP&E, Dr 1400 VAT, Cr 2000 AP) → payment run. Accruals with reversal, prepaid amortisation |
| Payroll | `payroll.py` | Gross pay, employer contributions, withholding, net pay from payroll accounts |
| Fixed assets | `fixed_assets.py` | Capitalisation, straight-line depreciation schedule, disposals with gain/loss |
| Intercompany | `intercompany.py` | Seller Dr 1150 / Cr 4500 and buyer Dr 6650 / Cr 2050, with the buyer booking 0-4 days later (cut-off timing differences) |
| Record-to-report | `journal_entries.py` | Opening balances, loans and interest, VAT settlement, quarterly income tax, IT cost allocation, error + reversal pairs, draft journals, annual dividend |
| Treasury | `treasury.py` | Multi-currency bank accounts, FX funding transfers and sweeps, bank fees and interest, month-end revaluation of foreign-currency cash |
| Closing | `closing.py` | Period calendar: soft close BD4, hard close BD8, a controlled reopen window |

## Currency rules (`config/financial-rules.yaml`)

* Rates are **target units per one source unit**, published against EUR. Cross rates are triangulated
  through EUR. A missing rate raises an error and never falls back to 1.0.
* Translation to EUR (IAS 21 style): assets and liabilities at the **closing** rate, equity at
  **historical** rates, P&L at the **monthly average** rate. The currency translation adjustment (CTA) is
  the balancing figure, and the test `assert_cta_zero_for_eur_entities` requires it to be zero for EUR
  entities.
* Rounding is ROUND_HALF_UP to the currency's minor unit (JPY has 0 decimals). Allocation residuals go to
  computed lines only.

## Consolidation

| Elimination | Matches | Difference posted to |
|---|---|---|
| `IC_REVENUE_EXPENSE` | 4500 IC revenue vs 6650 IC expense per entity pair and period | 8400 (consolidation-only) |
| `IC_BALANCES` | 1150 IC receivable vs 2050 IC payable | 1190 elimination suspense |
| `INVESTMENT_EQUITY` | Parent's investment vs subsidiary share capital | 3100 retained earnings |

Pairs that differ by more than 2% (`ic_tolerance_pct`) are reported as `MISMATCH` or `MISSING_COUNTERPART`.
Group net profit is the same before and after eliminations (`assert_consolidation_preserves_group_profit`).

## Planted scenarios (and where they surface)

| Scenario | Planted in | Detected by |
|---|---|---|
| Two GL-only AR adjustments: E04 2024-03-28 EUR 18,450 and E09 2025-05-30 EUR 27,300 (booked in USD) | `journal_entries.py` | `int_subledger_reconciliation` → `ACCOUNTS_RECEIVABLE_VS_GL` critical exceptions from the posting month onward. Test: `test_planted_gl_only_ar_adjustments_are_detected` |
| Duplicate supplier invoices, re-submitted 5-20 days later (about 70% blocked, the rest paid twice) | `procurement.py` | `DUPLICATE_INVOICE` / `POSSIBLE_DUPLICATE` exceptions. A blocked duplicate carries no liability |
| Price variance, short receipt, missing receipt, invoice without a PO | `procurement.py` | `int_three_way_matching` (price tolerance 2%) |
| Duplicate debit by the bank | `treasury.py` | Bank matching (`POSSIBLE_DUPLICATE`) |
| Bank fees booked 1-4 days after the bank date, receipts without a reference | `treasury.py`, `invoices.py` | `OUTSTANDING_NOT_YET_BOOKED` / `OUTSTANDING_IN_TRANSIT`, with a 5-day date tolerance |
| Intercompany cut-off differences | `intercompany.py` | `mart_intercompany_reconciliation` |
| Reopened period E06 2023-06 with an audit adjustment | `journal_entries.py`, `closing.py` | `stg_erp__period_status_changes`. Close-period tests accept this posting only inside the reopen window |
| FX: re-published correction, an invalid zero rate, a missing INR business day | `exchange_rates.py` | Latest valid publication wins. The zero rate is quarantined. A lookback covers the missing day |
| Duplicate and corrupted file deliveries (`--inject-failures`) | `source_systems/publish_files.py` | SHA-256 duplicate detection, file quarantine |

## Bank matching rules

1. **R1 BANK_ORIGINATED**: fees, interest and transfers that the bank generated carry the GL journal reference.
2. **R2 EXACT_REFERENCE**: same account, amount and payment reference.
3. **R3 AMOUNT_DATE**: same account and amount within ±5 calendar days. It is used only when exactly one
   candidate exists on each side, and never to pick between two.

## As-of reporting

AR/AP aging is rebuilt for every month end from dated settlement events. A payment received after the
reporting date does not change the aging at that date (`assert_historical_aging_ignores_later_payments`).
The supplier-invoice liability starts on the **GL posting date** (receipt), not on the supplier's invoice
date. That makes the AP subledger tie to the GL control account in every month.
