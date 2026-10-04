# Service boundary

Future domain services own requests and validate unknown response data before
passing it to components. Requests must use the shared same-origin `/api/v1`
transport. Components and hooks must not call provider endpoints or handle
provider credentials. The shell makes no API calls.
