// ClaimLens: resource-group-scoped deployment.
//   az group create -n rg-claimlens-dev -l eastus2
//   az deployment group create -g rg-claimlens-dev -f infra/main.bicep -p infra/parameters/dev.bicepparam
targetScope = 'resourceGroup'

@allowed(['dev', 'prod'])
param environment string = 'dev'
param location string = resourceGroup().location
@description('Short name used in resource names')
param workload string = 'claimlens'
@description('Microsoft Entra tenant that issues tokens for the API')
param entraTenantId string = subscription().tenantId
@description('Audience (application ID URI) the API accepts, e.g. api://<client-id>')
param entraAudience string
param apiImage string = ''
param workerImage string = ''
@description('Origin of the web app for CORS, e.g. https://xyz.azurestaticapps.net')
param webOrigin string = ''
param openAiLocation string = location
param deployModels bool = true
param docIntelSku string = environment == 'prod' ? 'S0' : 'F0'
param modelBlobPrefix string = ''
param useLlmExtraction bool = false
param useLlmExplanations bool = false
param webLocation string = 'eastus2'
@description('Object ID of the CI/CD service principal (gets write access to the models container only)')
param deployerPrincipalId string = ''

var isProd = environment == 'prod'
var prefix = '${workload}-${environment}'
var uniq = take(uniqueString(resourceGroup().id), 6)

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: { prefix: prefix, location: location, retentionDays: isProd ? 90 : 30 }
}

module identity 'modules/identity.bicep' = {
  name: 'identity'
  params: { prefix: prefix, location: location }
}

module data 'modules/data.bicep' = {
  name: 'data'
  params: { prefix: prefix, location: location, uniq: uniq, isProd: isProd, cosmosServerless: !isProd }
}

module messaging 'modules/messaging.bicep' = {
  name: 'messaging'
  params: { prefix: prefix, location: location, uniq: uniq }
}

module ai 'modules/ai.bicep' = {
  name: 'ai'
  params: {
    prefix: prefix
    location: location
    uniq: uniq
    isProd: isProd
    openAiLocation: openAiLocation
    deployModels: deployModels
    docIntelSku: docIntelSku
  }
}

module web 'modules/web.bicep' = {
  name: 'web'
  params: { prefix: prefix, location: webLocation, isProd: isProd }
}

module compute 'modules/compute.bicep' = {
  name: 'compute'
  params: {
    prefix: prefix
    location: location
    uniq: uniq
    isProd: isProd
    logAnalyticsName: monitoring.outputs.logAnalyticsName
    apiIdentityId: identity.outputs.apiId
    apiClientId: identity.outputs.apiClientId
    workerIdentityId: identity.outputs.workerId
    workerClientId: identity.outputs.workerClientId
    apiImage: apiImage
    workerImage: workerImage
    webOrigin: empty(webOrigin) ? 'https://${web.outputs.defaultHostname}' : webOrigin
    entraTenantId: entraTenantId
    entraAudience: entraAudience
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    blobEndpoint: data.outputs.blobEndpoint
    cosmosEndpoint: data.outputs.cosmosEndpoint
    serviceBusNamespace: messaging.outputs.fullyQualifiedNamespace
    serviceBusQueue: messaging.outputs.queueName
    docIntelEndpoint: ai.outputs.docIntelEndpoint
    openAiEndpoint: ai.outputs.openAiEndpoint
    searchEndpoint: ai.outputs.searchEndpoint
    modelBlobPrefix: modelBlobPrefix
    useLlmExtraction: useLlmExtraction
    useLlmExplanations: useLlmExplanations
  }
}

module rbac 'modules/rbac.bicep' = {
  name: 'rbac'
  params: {
    apiPrincipalId: identity.outputs.apiPrincipalId
    workerPrincipalId: identity.outputs.workerPrincipalId
    storageName: data.outputs.storageName
    serviceBusName: messaging.outputs.namespaceName
    docIntelName: ai.outputs.docIntelName
    openAiName: ai.outputs.openAiName
    searchName: ai.outputs.searchName
    cosmosName: data.outputs.cosmosName
    acrName: compute.outputs.acrName
    deployerPrincipalId: deployerPrincipalId
  }
}

output apiUrl string = 'https://${compute.outputs.apiFqdn}'
output webUrl string = 'https://${web.outputs.defaultHostname}'
output webAppName string = web.outputs.name
output acrName string = compute.outputs.acrName
output acrLoginServer string = compute.outputs.acrLoginServer
output apiAppName string = compute.outputs.apiName
output workerAppName string = compute.outputs.workerName
output storageAccount string = data.outputs.storageName
output searchEndpoint string = ai.outputs.searchEndpoint
