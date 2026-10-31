using '../main.bicep'

param environment = 'prod'
param entraAudience = 'api://00000000-0000-0000-0000-000000000000' // replace with your API app registration's application ID URI
param deployModels = true
param useLlmExtraction = true
param useLlmExplanations = true
