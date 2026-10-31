param prefix string
@description('Static Web Apps are only available in a few regions.')
param location string = 'eastus2'
param isProd bool = false

resource web 'Microsoft.Web/staticSites@2023-12-01' = {
  name: 'swa-${prefix}'
  location: location
  sku: { name: isProd ? 'Standard' : 'Free', tier: isProd ? 'Standard' : 'Free' }
  properties: {
    stagingEnvironmentPolicy: 'Enabled'
    allowConfigFileUpdates: true
  }
}

output name string = web.name
output defaultHostname string = web.properties.defaultHostname
