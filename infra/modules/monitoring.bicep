@description('Name prefix for resources')
param prefix string
param location string
param retentionDays int = 30

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${prefix}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionDays
    features: { disableLocalAuth: true }
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${prefix}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    DisableLocalAuth: false // the Python exporter uses the connection string; flip to true once AAD ingestion is wired
  }
}

output logAnalyticsId string = logs.id
output logAnalyticsName string = logs.name
output appInsightsConnectionString string = appi.properties.ConnectionString
