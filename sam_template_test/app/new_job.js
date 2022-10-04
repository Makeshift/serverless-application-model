exports.handler = async function handler (event, context) {
  console.log('Received event:', JSON.stringify(event, null, 2))
  return {
    statusCode: 200,
    body: 'Hello world!'
  }
}
