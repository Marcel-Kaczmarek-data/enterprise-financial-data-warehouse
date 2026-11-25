# ADR 0004: Historical aging from dated settlement events

**Status:** accepted

## Context
Source systems keep only the *current* open amount of an invoice. An aging report for a past month end
built from that amount is wrong as soon as the invoice is paid later.

## Decision
Build an event stream per document: issue (dated by the **GL posting date**), payments, discounts,
credit notes, write-offs and refunds. The outstanding amount at any reporting date is the sum of the
events up to that date.

## Consequences
* Aging and DSO/DPO history do not change when later payments arrive
  (`assert_historical_aging_ignores_later_payments`).
* The subledger ties to the GL control accounts at every month end. AP ties exactly, and AR differs
  only by the two planted GL-only adjustments.
