param prefix string
param location string
param uniq string
param maxDeliveryCount int = 5

resource ns 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: 'sb-${prefix}-${uniq}'
  location: location
  sku: { name: 'Standard', tier: 'Standard' } // Standard is required for duplicate detection
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
  }
}

resource queue 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = {
  parent: ns
  name: 'claim-jobs'
  properties: {
    lockDuration: 'PT5M' // a claim with several scans can take a few minutes
    maxDeliveryCount: maxDeliveryCount
    deadLetteringOnMessageExpiration: true
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'PT10M'
    defaultMessageTimeToLive: 'P1D'
  }
}

output namespaceName string = ns.name
output namespaceId string = ns.id
output fullyQualifiedNamespace string = '${ns.name}.servicebus.windows.net'
output queueName string = queue.name
