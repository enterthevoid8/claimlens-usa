param prefix string
param location string
param uniq string
@description('Cosmos DB: serverless is cheapest for spiky or low volume; switch to provisioned autoscale when traffic is steady.')
param cosmosServerless bool = true
param isProd bool = false
param blobDeleteRetentionDays int = 7

var storageName = take('stcl${replace(prefix, '-', '')}${uniq}', 24)

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: isProd ? 'Standard_ZRS' : 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false // Entra ID only: no account keys to leak
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Enabled' // tighten with private endpoints for production (see docs/SECURITY.md)
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: blobDeleteRetentionDays }
    containerDeleteRetentionPolicy: { enabled: true, days: blobDeleteRetentionDays }
  }
}

resource claimsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'claims'
  properties: { publicAccess: 'None' }
}

// Model bundles live apart from claim documents: the API and worker may read them but never write them.
resource modelsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'models'
  properties: { publicAccess: 'None' }
}

// Blobs older than 90 days are removed: documents are only needed while a claim is open.
resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'expire-raw-documents'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: { blobTypes: ['blockBlob'], prefixMatch: ['claims/raw/'] }
            actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: 90 } } }
          }
        }
      ]
    }
  }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: 'cosmos-${prefix}-${uniq}'
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [{ locationName: location, failoverPriority: 0, isZoneRedundant: false }]
    capabilities: cosmosServerless ? [{ name: 'EnableServerless' }] : []
    disableLocalAuth: true // Entra ID data-plane roles only
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    backupPolicy: { type: 'Continuous', continuousModeProperties: { tier: 'Continuous7Days' } }
    publicNetworkAccess: 'Enabled'
  }
}

resource db 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: 'claimlens'
  properties: { resource: { id: 'claimlens' } }
}

var containerNames = ['claims', 'policies', 'audit']

resource containers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = [for name in containerNames: {
  parent: db
  name: name
  properties: {
    resource: {
      id: name
      partitionKey: { paths: ['/tenantId'], kind: 'Hash', version: 2 }
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [{ path: '/status/?' }, { path: '/submitted_by/?' }, { path: '/created_at/?' }, { path: '/resource/?' }]
        excludedPaths: [{ path: '/*' }] // the big nested analysis document is never queried by field
      }
    }
  }
}]

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take('kv-${prefix}-${uniq}', 24)
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
    enablePurgeProtection: isProd ? true : null
  }
}

output storageName string = storage.name
output storageId string = storage.id
output blobEndpoint string = storage.properties.primaryEndpoints.blob
output cosmosName string = cosmos.name
output cosmosId string = cosmos.id
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output keyVaultName string = kv.name
