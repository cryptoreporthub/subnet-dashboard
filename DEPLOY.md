# Deployment Notes

## Version 3.3.1
- Added technical indicators (RSI, MACD, MA Cross) to mindmap summary
- Added rotation tokens endpoint: `/api/rotation-tokens`
- Learning loop enabled with feedback collection

## Deployment Steps
1. `flyctl deploy --app subnet-dashboard --remote-only`
2. Verify endpoints:
   - `/health` - returns "OK"
   - `/api/mindmap/summary` - returns summary with technical indicators
   - `/api/rotation-tokens` - returns the 5 rotation tokens