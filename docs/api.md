# Klerno Labs - API Documentation

## Overview

The Klerno Labs API provides programmatic access to our AML risk intelligence platform. Built on FastAPI, it offers high-performance, secure, and well-documented endpoints for transaction analysis, risk scoring, and compliance automation.

**Base URL**: `https://api.klerno.com`  
**API Version**: `v1`  
**Authentication**: API Key based  

## Quick Start

### Authentication

All API requests require an API key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-api-key-here" \
     https://api.klerno.com/v1/health
```

### Getting Your API Key

1. Log in to your Klerno Labs dashboard
2. Navigate to **Settings** → **API Keys**
3. Generate a new API key
4. Store it securely (it won't be shown again)

## Core Endpoints

### Health Check
**GET** `/health`

Check API service status.

```bash
curl -H "X-API-Key: your-key" \
     https://api.klerno.com/health
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-27T12:00:00Z",
  "version": "1.0.0",
  "services": {
    "database": "online",
    "xrpl": "connected",
    "ai_engine": "ready"
  }
}
```

### Transaction Analysis
**POST** `/analyze/transaction`

Analyze a single transaction for risk factors.

```bash
curl -X POST \
     -H "X-API-Key: your-key" \
     -H "Content-Type: application/json" \
     -d '{
       "tx_id": "ABC123...",
       "amount": 10000,
       "from_address": "rFrom...",
       "to_address": "rTo...",
       "chain": "XRP"
     }' \
     https://api.klerno.com/analyze/transaction
```

**Response:**
```json
{
  "transaction": {
    "tx_id": "ABC123...",
    "risk_score": 0.75,
    "risk_category": "medium",
    "risk_flags": ["large_amount", "new_address"],
    "explanation": "Transaction flagged due to large amount and new recipient address.",
    "confidence": 0.89
  },
  "compliance": {
    "category": "large_payment",
    "requires_review": true,
    "regulatory_flags": ["CTR_threshold"]
  }
}
```

### Batch Analysis
**POST** `/analyze/batch`

Analyze multiple transactions in a single request.

```bash
curl -X POST \
     -H "X-API-Key: your-key" \
     -H "Content-Type: application/json" \
     -d '{
       "transactions": [
         {
           "tx_id": "TX1",
           "amount": 5000,
           "from_address": "rFrom1",
           "to_address": "rTo1"
         },
         {
           "tx_id": "TX2", 
           "amount": 15000,
           "from_address": "rFrom2",
           "to_address": "rTo2"
         }
       ]
     }' \
     https://api.klerno.com/analyze/batch
```

### Risk Scoring
**GET** `/risk/score/{tx_id}`

Get detailed risk scoring for a specific transaction.

```bash
curl -H "X-API-Key: your-key" \
     https://api.klerno.com/risk/score/ABC123
```

**Response:**
```json
{
  "tx_id": "ABC123",
  "risk_score": 0.75,
  "risk_breakdown": {
    "amount_risk": 0.8,
    "address_risk": 0.6,
    "timing_risk": 0.3,
    "pattern_risk": 0.9
  },
  "risk_factors": [
    {
      "factor": "large_amount",
      "impact": 0.7,
      "description": "Transaction amount exceeds typical patterns"
    }
  ]
}
```

### Compliance Reports
**GET** `/reports/compliance`

Generate compliance reports for specified date ranges.

**Parameters:**
- `start_date` (string): Start date (YYYY-MM-DD)
- `end_date` (string): End date (YYYY-MM-DD)
- `format` (string): Output format (json, csv, pdf)
- `type` (string): Report type (summary, detailed, sar)

```bash
curl -H "X-API-Key: your-key" \
     "https://api.klerno.com/reports/compliance?start_date=2025-01-01&end_date=2025-01-31&format=json&type=summary"
```

### Address Monitoring
**POST** `/monitor/address`

Add an address to your monitoring list.

```bash
curl -X POST \
     -H "X-API-Key: your-key" \
     -H "Content-Type: application/json" \
     -d '{
       "address": "rMonitorMe123...",
       "label": "High Risk Exchange",
       "risk_level": "high",
       "notes": "Flagged by compliance team"
     }' \
     https://api.klerno.com/monitor/address
```

### Alerts
**GET** `/alerts`

Retrieve active alerts for your account.

**Parameters:**
- `status` (string): Alert status (active, resolved, all)
- `risk_level` (string): Minimum risk level (low, medium, high)
- `limit` (int): Maximum number of alerts to return
- `offset` (int): Pagination offset

```bash
curl -H "X-API-Key: your-key" \
     "https://api.klerno.com/alerts?status=active&risk_level=high&limit=50"
```

## Response Formats

### Standard Response Structure
```json
{
  "success": true,
  "data": { ... },
  "meta": {
    "timestamp": "2025-01-27T12:00:00Z",
    "request_id": "req_abc123",
    "processing_time": 0.045
  }
}
```

### Error Response Structure
```json
{
  "success": false,
  "error": {
    "code": "INVALID_REQUEST",
    "message": "Missing required field: tx_id",
    "details": {
      "field": "tx_id",
      "expected": "string"
    }
  },
  "meta": {
    "timestamp": "2025-01-27T12:00:00Z",
    "request_id": "req_error123"
  }
}
```

## Rate Limits

| Plan | Requests/Hour | Burst Limit |
|------|---------------|-------------|
| Free | 100 | 10/minute |
| Professional | 10,000 | 100/minute |
| Enterprise | 100,000 | 1000/minute |

When rate limits are exceeded, you'll receive a `429 Too Many Requests` response.

## Error Codes

| Code | Description |
|------|-------------|
| `INVALID_API_KEY` | API key is invalid or expired |
| `INSUFFICIENT_PERMISSIONS` | API key lacks required permissions |
| `INVALID_REQUEST` | Request format or parameters are invalid |
| `RESOURCE_NOT_FOUND` | Requested resource doesn't exist |
| `RATE_LIMIT_EXCEEDED` | Too many requests in time window |
| `INTERNAL_ERROR` | Server-side error occurred |

## SDKs and Libraries

### Python SDK
```bash
pip install klerno-labs-sdk
```

```python
from klerno import KlernoClient

client = KlernoClient(api_key="your-key")
result = client.analyze_transaction({
    "tx_id": "ABC123",
    "amount": 10000,
    "from_address": "rFrom",
    "to_address": "rTo"
})
```

### JavaScript SDK
```bash
npm install @klerno-labs/sdk
```

```javascript
import { KlernoClient } from '@klerno-labs/sdk';

const client = new KlernoClient({ apiKey: 'your-key' });
const result = await client.analyzeTransaction({
  txId: 'ABC123',
  amount: 10000,
  fromAddress: 'rFrom',
  toAddress: 'rTo'
});
```

## Webhooks

Configure webhooks to receive real-time notifications about high-risk transactions and system events.

### Setup
1. Go to **Settings** → **Webhooks** in your dashboard
2. Add your endpoint URL
3. Select event types to receive
4. Configure authentication method

### Event Types
- `transaction.high_risk` - High-risk transaction detected
- `alert.created` - New alert generated
- `compliance.threshold_exceeded` - Compliance threshold exceeded
- `system.maintenance` - Scheduled maintenance notifications

### Example Webhook Payload
```json
{
  "event": "transaction.high_risk",
  "timestamp": "2025-01-27T12:00:00Z",
  "data": {
    "tx_id": "ABC123",
    "risk_score": 0.89,
    "amount": 25000,
    "from_address": "rFrom",
    "to_address": "rTo",
    "risk_flags": ["large_amount", "velocity_spike"]
  }
}
```

## Best Practices

### Security
- Store API keys securely and never commit them to version control
- Use HTTPS for all API requests
- Implement proper error handling and retry logic
- Monitor your API usage and set up alerts

### Performance
- Use batch endpoints when analyzing multiple transactions
- Implement caching for frequently accessed data
- Use pagination for large result sets
- Consider using webhooks instead of polling for real-time updates

### Reliability
- Implement exponential backoff for retries
- Handle rate limiting gracefully
- Monitor API health and status pages
- Have fallback mechanisms for critical operations

## Support

- **Documentation**: [docs.klerno.com](https://docs.klerno.com)
- **API Status**: [status.klerno.com](https://status.klerno.com)
- **Support Email**: [api-support@klerno.com](mailto:api-support@klerno.com)
- **Discord Community**: [discord.gg/klerno](https://discord.gg/klerno)

## Changelog

### v1.0.0 (2025-01-27)
- Initial API release
- Transaction analysis endpoints
- Risk scoring system
- Compliance reporting
- Webhook support

---

*For more detailed examples and advanced usage, visit our [API Explorer](https://api.klerno.com/docs).*