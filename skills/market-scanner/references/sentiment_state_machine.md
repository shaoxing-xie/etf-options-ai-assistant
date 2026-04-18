# Sentiment state machine

## State labels

- `ice_point`
- `repair`
- `climax`
- `ebb`

## Priority

1. If broken-board risk dominates and limit-up count is very low, use `ice_point`.
2. If breadth improves and limit-up count normalizes, use `repair`.
3. If breadth and board height both expand aggressively, use `climax`.
4. If high-level leaders fail and breadth deteriorates, use `ebb`.

