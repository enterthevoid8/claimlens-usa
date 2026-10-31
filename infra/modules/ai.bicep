param prefix string
param location string
param uniq string
param isProd bool = false
@description('Azure OpenAI region. Not every region offers every model: check availability before changing.')
param openAiLocation string = location
param chatModelName string = 'gpt-4o-mini'
param chatModelVersion string = '2024-07-18'
param embeddingModelName string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'
param chatCapacity int = 30
param embeddingCapacity int = 30
@description('Free tiers are limited to one per subscription; use S0 when one already exists.')
param docIntelSku string = isProd ? 'S0' : 'F0'
param searchSku string = isProd ? 'basic' : 'free'
@description('Deploy the model deployments (needs Azure OpenAI quota). Turn off for a first dry run.')
param deployModels bool = true

resource docIntel 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: 'di-${prefix}-${uniq}'
  location: location
  kind: 'FormRecognizer'
  sku: { name: docIntelSku }
  properties: {
    customSubDomainName: 'di-${prefix}-${uniq}' // required for Entra ID auth
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource openai 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: 'oai-${prefix}-${uniq}'
  location: openAiLocation
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: 'oai-${prefix}-${uniq}'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = if (deployModels) {
  parent: openai
  name: 'chat'
  sku: { name: 'Standard', capacity: chatCapacity }
  properties: { model: { format: 'OpenAI', name: chatModelName, version: chatModelVersion } }
}

resource embedding 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = if (deployModels) {
  parent: openai
  name: 'embedding'
  dependsOn: [chat] // deployments on one account are created serially
  sku: { name: 'Standard', capacity: embeddingCapacity }
  properties: { model: { format: 'OpenAI', name: embeddingModelName, version: embeddingModelVersion } }
}

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: 'srch-${prefix}-${uniq}'
  location: location
  sku: { name: searchSku }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    // Keys are disabled in prod. The free tier may not support role-based access: if the deployment rejects it, deploy dev with key auth.
    disableLocalAuth: isProd
    authOptions: isProd ? null : { aadOrApiKey: { aadAuthFailureMode: 'http401WithBearerChallenge' } }
    semanticSearch: searchSku == 'free' ? 'free' : 'standard'
  }
}

output docIntelName string = docIntel.name
output docIntelEndpoint string = docIntel.properties.endpoint
output openAiName string = openai.name
output openAiEndpoint string = openai.properties.endpoint
output searchName string = search.name
output searchEndpoint string = 'https://${search.name}.search.windows.net'
