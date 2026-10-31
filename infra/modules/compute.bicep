param prefix string
param location string
param uniq string
param isProd bool = false
param logAnalyticsName string
param apiIdentityId string
param apiClientId string
param workerIdentityId string
param workerClientId string
@description('Full image reference for the API. Leave empty on the first deployment: a placeholder image is used until CI pushes the real one.')
param apiImage string = ''
param workerImage string = ''
param webOrigin string = ''
param entraTenantId string
param entraAudience string
param appInsightsConnectionString string
param blobEndpoint string
param cosmosEndpoint string
param serviceBusNamespace string
param serviceBusQueue string
param docIntelEndpoint string
param openAiEndpoint string
param searchEndpoint string
param modelBlobPrefix string = ''
param useLlmExtraction bool = false
param useLlmExplanations bool = false
param workerMaxReplicas int = 5

var bootstrapImage = 'mcr.microsoft.com/k8se/quickstart:latest'
var isBootstrap = empty(apiImage)

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = { name: logAnalyticsName }

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: take('acrcl${replace(prefix, '-', '')}${uniq}', 50)
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${prefix}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey }
    }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
  }
}

var commonEnv = [
  { name: 'CLAIMLENS_ENVIRONMENT', value: isProd ? 'prod' : 'dev' }
  { name: 'CLAIMLENS_BACKEND', value: 'azure' }
  { name: 'CLAIMLENS_AUTH_MODE', value: 'entra' }
  { name: 'CLAIMLENS_ENTRA_TENANT_ID', value: entraTenantId }
  { name: 'CLAIMLENS_ENTRA_AUDIENCE', value: entraAudience }
  { name: 'CLAIMLENS_STORAGE_ACCOUNT_URL', value: blobEndpoint }
  { name: 'CLAIMLENS_COSMOS_ENDPOINT', value: cosmosEndpoint }
  { name: 'CLAIMLENS_SERVICEBUS_NAMESPACE', value: serviceBusNamespace }
  { name: 'CLAIMLENS_SERVICEBUS_QUEUE', value: serviceBusQueue }
  { name: 'CLAIMLENS_DOCINTEL_ENDPOINT', value: docIntelEndpoint }
  { name: 'CLAIMLENS_OPENAI_ENDPOINT', value: openAiEndpoint }
  { name: 'CLAIMLENS_OPENAI_DEPLOYMENT', value: 'chat' }
  { name: 'CLAIMLENS_OPENAI_EMBEDDING_DEPLOYMENT', value: 'embedding' }
  { name: 'CLAIMLENS_SEARCH_ENDPOINT', value: searchEndpoint }
  { name: 'CLAIMLENS_APPINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
  { name: 'CLAIMLENS_MODEL_BLOB_PREFIX', value: modelBlobPrefix }
  { name: 'CLAIMLENS_USE_LLM_EXTRACTION', value: string(useLlmExtraction) }
  { name: 'CLAIMLENS_USE_LLM_EXPLANATIONS', value: string(useLlmExplanations) }
  { name: 'CLAIMLENS_CORS_ORIGINS', value: empty(webOrigin) ? '[]' : '["${webOrigin}"]' }
]

resource api 'Microsoft.App/containerApps@2025-01-01' = {
  name: 'ca-${prefix}-api'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${apiIdentityId}': {} } }
  properties: {
    managedEnvironmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: { external: true, targetPort: isBootstrap ? 80 : 8000, transport: 'auto', allowInsecure: false }
      registries: isBootstrap ? [] : [{ server: acr.properties.loginServer, identity: apiIdentityId }]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: isBootstrap ? bootstrapImage : apiImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat(commonEnv, [{ name: 'AZURE_CLIENT_ID', value: apiClientId }])
          probes: isBootstrap ? [] : [
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 20 }
            { type: 'Readiness', httpGet: { path: '/readyz', port: 8000 }, periodSeconds: 10 }
          ]
        }
      ]
      scale: {
        minReplicas: isProd ? 2 : 0
        maxReplicas: isProd ? 10 : 2
        rules: [{ name: 'http', http: { metadata: { concurrentRequests: '40' } } }]
      }
    }
  }
}

resource worker 'Microsoft.App/containerApps@2025-01-01' = {
  name: 'ca-${prefix}-worker'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${workerIdentityId}': {} } }
  properties: {
    managedEnvironmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      registries: isBootstrap || empty(workerImage) ? [] : [{ server: acr.properties.loginServer, identity: workerIdentityId }]
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: empty(workerImage) ? bootstrapImage : workerImage
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: concat(commonEnv, [{ name: 'AZURE_CLIENT_ID', value: workerClientId }])
        }
      ]
      scale: {
        minReplicas: 0 // scale to zero when the queue is empty
        maxReplicas: workerMaxReplicas
        rules: [
          {
            name: 'queue-depth'
            custom: {
              type: 'azure-servicebus'
              metadata: { queueName: serviceBusQueue, namespace: split(serviceBusNamespace, '.')[0], messageCount: '5' }
              identity: workerIdentityId // KEDA authenticates with the worker's managed identity: no connection string
            }
          }
        ]
      }
    }
  }
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output apiName string = api.name
output workerName string = worker.name
output apiFqdn string = api.properties.configuration.ingress.fqdn
