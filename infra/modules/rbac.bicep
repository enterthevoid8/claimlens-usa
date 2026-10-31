// Least-privilege data-plane roles. Each identity gets only what its process does.
param apiPrincipalId string
param workerPrincipalId string
param storageName string
param serviceBusName string
param docIntelName string
param openAiName string
param searchName string
param cosmosName string
param acrName string
@description('Object ID of the CI/CD identity that publishes model bundles (optional)')
param deployerPrincipalId string = ''

var role = {
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  serviceBusSender: '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
  serviceBusReceiver: '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  searchIndexDataReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
}
var cosmosDataContributor = '00000000-0000-0000-0000-000000000002' // built-in "Cosmos DB Built-in Data Contributor"

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = { name: storageName }
resource blobSvc 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = { parent: storage, name: 'default' }
resource claimsBlobs 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = { parent: blobSvc, name: 'claims' }
resource modelBlobs 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = { parent: blobSvc, name: 'models' }
resource sb 'Microsoft.ServiceBus/namespaces@2024-01-01' existing = { name: serviceBusName }
resource di 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = { name: docIntelName }
resource oai 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = { name: openAiName }
resource search 'Microsoft.Search/searchServices@2023-11-01' existing = { name: searchName }
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = { name: cosmosName }
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = { name: acrName }

// ---- API: uploads documents, enqueues jobs, reads/writes claims, answers questions
resource apiBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(claimsBlobs.id, apiPrincipalId, role.storageBlobDataContributor)
  scope: claimsBlobs
  properties: { principalId: apiPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.storageBlobDataContributor) }
}
resource apiSend 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sb.id, apiPrincipalId, role.serviceBusSender)
  scope: sb
  properties: { principalId: apiPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.serviceBusSender) }
}
resource apiOai 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(oai.id, apiPrincipalId, role.openAiUser)
  scope: oai
  properties: { principalId: apiPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.openAiUser) }
}
resource apiSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, apiPrincipalId, role.searchIndexDataReader)
  scope: search
  properties: { principalId: apiPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.searchIndexDataReader) }
}
resource apiPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, apiPrincipalId, role.acrPull)
  scope: acr
  properties: { principalId: apiPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.acrPull) }
}
resource apiCosmos 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, apiPrincipalId, cosmosDataContributor)
  properties: { roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributor}', principalId: apiPrincipalId, scope: cosmos.id }
}

// ---- Worker: reads documents, receives jobs, runs OCR/LLM, writes analyses, indexes clauses
resource workerBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(claimsBlobs.id, workerPrincipalId, role.storageBlobDataReader)
  scope: claimsBlobs
  properties: { principalId: workerPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.storageBlobDataReader) }
}
resource workerReceive 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sb.id, workerPrincipalId, role.serviceBusReceiver)
  scope: sb
  properties: { principalId: workerPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.serviceBusReceiver) }
}
resource workerDi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(di.id, workerPrincipalId, role.cognitiveServicesUser)
  scope: di
  properties: { principalId: workerPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.cognitiveServicesUser) }
}
resource workerOai 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(oai.id, workerPrincipalId, role.openAiUser)
  scope: oai
  properties: { principalId: workerPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.openAiUser) }
}
resource workerSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, workerPrincipalId, role.searchIndexDataContributor)
  scope: search
  properties: { principalId: workerPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.searchIndexDataContributor) }
}
resource workerPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, workerPrincipalId, role.acrPull)
  scope: acr
  properties: { principalId: workerPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.acrPull) }
}
resource workerCosmos 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, workerPrincipalId, cosmosDataContributor)
  properties: { roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributor}', principalId: workerPrincipalId, scope: cosmos.id }
}

// ---- Both processes read (never write) the signed-off model bundle
resource apiModels 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(modelBlobs.id, apiPrincipalId, role.storageBlobDataReader)
  scope: modelBlobs
  properties: { principalId: apiPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.storageBlobDataReader) }
}
resource workerModels 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(modelBlobs.id, workerPrincipalId, role.storageBlobDataReader)
  scope: modelBlobs
  properties: { principalId: workerPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.storageBlobDataReader) }
}

// ---- CI/CD publishes model bundles; it cannot touch claim documents
resource deployerModels 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(modelBlobs.id, deployerPrincipalId, role.storageBlobDataContributor)
  scope: modelBlobs
  properties: { principalId: deployerPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.storageBlobDataContributor) }
}
