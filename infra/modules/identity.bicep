param prefix string
param location string

resource api 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${prefix}-api'
  location: location
}

resource worker 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${prefix}-worker'
  location: location
}

output apiId string = api.id
output apiPrincipalId string = api.properties.principalId
output apiClientId string = api.properties.clientId
output workerId string = worker.id
output workerPrincipalId string = worker.properties.principalId
output workerClientId string = worker.properties.clientId
