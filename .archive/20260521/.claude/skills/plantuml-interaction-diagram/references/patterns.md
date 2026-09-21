# Common Interaction Diagram Patterns

Reusable PlantUML sequence diagram patterns for frequently encountered system interactions. Each pattern includes a complete PlantUML source block, a description of when to use it, and customization notes.

## Pattern 1: REST API Authentication Flow

### When to Use

Any system where a client authenticates with credentials and receives tokens. Covers login, token validation, and refresh.

### PlantUML Source

```plantuml
@startuml auth-flow
!theme plain
title Authentication Flow

box "Client" #E3F2FD
  actor User
  participant "Web App" as App
end box

box "Backend" #E8F5E9
  boundary "API Gateway" as GW
  control "Auth Controller" as Auth
  entity "Token Service" as Token
end box

database "User DB" as DB

== Login ==
User -> App: enter credentials
App -> GW: POST /auth/login
GW -> Auth ++: authenticate(credentials)
Auth -> DB: findByEmail(email)
DB --> Auth: userRecord

alt valid credentials
  Auth -> Token: generateTokenPair(userId)
  Token --> Auth: {accessToken, refreshToken}
  Auth --> GW --: 200 {tokens}
  GW --> App: 200 {tokens}
  App --> User: redirect to dashboard
else invalid credentials
  Auth --> GW --: 401 Unauthorized
  GW --> App: 401 Unauthorized
  App --> User: show error message
end

== Token Refresh ==
App -> GW: POST /auth/refresh
GW -> Auth ++: refreshToken(token)
Auth -> Token: validate(refreshToken)

alt token valid
  Token --> Auth: claims
  Auth -> Token: generateTokenPair(userId)
  Token --> Auth: {newAccessToken, newRefreshToken}
  Auth --> GW --: 200 {tokens}
  GW --> App: 200 {tokens}
else token expired
  Auth --> GW --: 401 Token Expired
  GW --> App: 401 Token Expired
  App --> User: redirect to login
end

@enduml
```

### Customization Points

- Add `opt MFA enabled` block between credential validation and token generation for multi-factor auth.
- Replace `POST /auth/login` with OAuth or SSO endpoints as needed.
- Add rate limiting with a `break` fragment before authentication.

## Pattern 2: REST API CRUD Operations

### When to Use

Standard create-read-update-delete operations on a resource via a RESTful API.

### PlantUML Source

```plantuml
@startuml crud-api
!theme plain
title REST API CRUD Operations - /api/orders

actor Client
boundary "API Gateway" as GW
control "Order Controller" as Ctrl
entity "Order Service" as Svc
database "Database" as DB

== Create ==
Client -> GW: POST /api/orders {data}
GW -> Ctrl ++: createOrder(data)
Ctrl -> Svc: validate(data)
Svc -> DB: INSERT order
DB --> Svc: orderRecord
Svc --> Ctrl: order
Ctrl --> GW --: 201 Created {order}
GW --> Client: 201 Created

== Read ==
Client -> GW: GET /api/orders/{id}
GW -> Ctrl ++: getOrder(id)
Ctrl -> Svc: findById(id)
Svc -> DB: SELECT * WHERE id=?
alt found
  DB --> Svc: orderRecord
  Svc --> Ctrl: order
  Ctrl --> GW --: 200 OK {order}
  GW --> Client: 200 OK
else not found
  DB --> Svc: null
  Svc --> Ctrl: NotFoundException
  Ctrl --> GW --: 404 Not Found
  GW --> Client: 404 Not Found
end

== Update ==
Client -> GW: PUT /api/orders/{id} {data}
GW -> Ctrl ++: updateOrder(id, data)
Ctrl -> Svc: validate(data)
Svc -> DB: UPDATE orders SET ... WHERE id=?
DB --> Svc: updatedRecord
Svc --> Ctrl: order
Ctrl --> GW --: 200 OK {order}
GW --> Client: 200 OK

== Delete ==
Client -> GW: DELETE /api/orders/{id}
GW -> Ctrl ++: deleteOrder(id)
Ctrl -> Svc: softDelete(id)
Svc -> DB: UPDATE orders SET deleted=true WHERE id=?
DB --> Svc: ok
Svc --> Ctrl: void
Ctrl --> GW --: 204 No Content
GW --> Client: 204 No Content

@enduml
```

### Customization Points

- Replace `/api/orders` with the actual resource endpoint.
- Add authorization checks before each operation.
- Add pagination to the Read section for list endpoints.

## Pattern 3: Microservice Choreography (Event-Driven)

### When to Use

Multiple microservices communicating through events/messages without a central orchestrator.

### PlantUML Source

```plantuml
@startuml event-driven
!theme plain
title Event-Driven Order Processing

actor Customer
participant "Order Service" as Orders
queue "Event Bus" as Bus
participant "Payment Service" as Payment
participant "Inventory Service" as Inventory
participant "Notification Service" as Notify
database "Order DB" as OrderDB
database "Payment DB" as PayDB

Customer -> Orders ++: placeOrder(items, payment)
Orders -> OrderDB: save(order, status=PENDING)
OrderDB --> Orders: saved
Orders ->> Bus: emit OrderCreated
Orders --> Customer --: 202 Accepted {orderId}

== Payment Processing ==
Bus ->> Payment ++: OrderCreated event
Payment -> PayDB: chargeCard(payment)

alt payment successful
  PayDB --> Payment: charged
  Payment ->> Bus: emit PaymentCompleted
  deactivate Payment
else payment failed
  PayDB --> Payment: declined
  Payment ->> Bus: emit PaymentFailed
  deactivate Payment
end

== Inventory and Notification (Parallel) ==
par process order
  Bus ->> Inventory ++: PaymentCompleted event
  Inventory -> Inventory: reserveStock(items)
  Inventory ->> Bus: emit StockReserved
  deactivate Inventory
and
  Bus ->> Notify ++: PaymentCompleted event
  Notify -> Customer: sendConfirmationEmail()
  deactivate Notify
end

== Order Finalization ==
Bus ->> Orders ++: StockReserved event
Orders -> OrderDB: updateStatus(CONFIRMED)
OrderDB --> Orders: updated
deactivate Orders

note over Bus
  Events are durable and
  processed at-least-once
end note

@enduml
```

### Customization Points

- Add a `break` fragment for `PaymentFailed` to show compensation/rollback logic.
- Replace the event bus with specific technology names (Kafka, RabbitMQ, SNS/SQS).
- Add retry logic with `loop max 3 retries` around event processing.

## Pattern 4: Saga Pattern (Orchestration)

### When to Use

Distributed transactions coordinated by a central orchestrator that manages compensating transactions on failure.

### PlantUML Source

```plantuml
@startuml saga-orchestrator
!theme plain
title Saga Pattern - Order Processing

control "Saga Orchestrator" as Saga
participant "Order Service" as Orders
participant "Payment Service" as Payment
participant "Inventory Service" as Inventory
participant "Shipping Service" as Shipping

Saga -> Orders ++: createOrder()
Orders --> Saga --: orderCreated

Saga -> Payment ++: processPayment()
Payment --> Saga --: paymentProcessed

Saga -> Inventory ++: reserveInventory()

alt inventory available
  Inventory --> Saga --: inventoryReserved

  Saga -> Shipping ++: scheduleShipment()
  Shipping --> Saga --: shipmentScheduled

  Saga -> Orders: updateStatus(CONFIRMED)
else inventory unavailable
  Inventory --> Saga --: inventoryFailed

  note over Saga #FFAAAA
    Compensating transactions
  end note

  == Compensation ==
  Saga -> Payment: refundPayment()
  Payment --> Saga: refunded
  Saga -> Orders: cancelOrder()
  Orders --> Saga: cancelled
end

@enduml
```

### Customization Points

- Add timeout handling between steps.
- Include more compensation steps for complex workflows.
- Add state tracking with notes (`note over Saga: state = PAYMENT_PENDING`).

## Pattern 5: Circuit Breaker

### When to Use

Showing how a client handles failures from an unreliable downstream service using the circuit breaker pattern.

### PlantUML Source

```plantuml
@startuml circuit-breaker
!theme plain
title Circuit Breaker Pattern

participant "Client" as Client
control "Circuit Breaker" as CB
participant "Downstream Service" as Downstream
entity "Fallback" as Fallback

== Closed State (Normal Operation) ==
Client -> CB ++: request()
CB -> Downstream ++: forward request
Downstream --> CB --: response
CB --> Client --: response

== Open State (After Failures) ==
Client -> CB ++: request()

note right of CB #FFAAAA
  Failure threshold exceeded.
  Circuit is OPEN.
end note

CB -> Fallback: getCachedResponse()
Fallback --> CB: cached data
CB --> Client --: degraded response

== Half-Open State (Testing Recovery) ==
... after timeout period ...

Client -> CB ++: request()

note right of CB #FFFFAA
  Circuit is HALF-OPEN.
  Allowing test request.
end note

CB -> Downstream ++: test request

alt service recovered
  Downstream --> CB --: success
  CB --> Client --: response
  note right of CB #AAFFAA: Circuit CLOSED
else still failing
  Downstream --> CB --: error
  CB -> Fallback: getCachedResponse()
  Fallback --> CB: cached data
  CB --> Client --: degraded response
  note right of CB #FFAAAA: Circuit remains OPEN
end

@enduml
```

## Pattern 6: WebSocket / Real-Time Communication

### When to Use

Bidirectional real-time communication between client and server.

### PlantUML Source

```plantuml
@startuml websocket
!theme plain
title WebSocket Communication

actor User
participant "Browser" as Browser
boundary "WS Gateway" as WS
control "Chat Service" as Chat
database "Message DB" as DB
queue "Pub/Sub" as PubSub

== Connection Setup ==
User -> Browser: open chat
Browser -> WS: WebSocket handshake
WS --> Browser: 101 Switching Protocols
Browser -> WS: subscribe(room=general)
WS -> PubSub: subscribe(channel=room:general)

== Send Message ==
User -> Browser: type message
Browser -> WS: send({type: "message", text: "hello"})
WS -> Chat ++: handleMessage(msg)
Chat -> DB: save(message)
DB --> Chat: saved
Chat -> PubSub: publish(channel=room:general, msg)
deactivate Chat

== Receive Message (Fan-out) ==
PubSub ->> WS: message event
WS ->> Browser: push({type: "message", from: "Alice", text: "hello"})
Browser --> User: display message

== Disconnect ==
User -> Browser: close tab
Browser -> WS: close connection
WS -> PubSub: unsubscribe(channel=room:general)

@enduml
```

## Pattern 7: Batch Processing Pipeline

### When to Use

Data pipeline with staged processing, typically for ETL or batch job workflows.

### PlantUML Source

```plantuml
@startuml batch-pipeline
!theme plain
title Batch Processing Pipeline

control "Scheduler" as Sched
participant "Extractor" as Extract
queue "Raw Queue" as RawQ
participant "Transformer" as Transform
queue "Processed Queue" as ProcQ
participant "Loader" as Load
database "Data Warehouse" as DW

Sched -> Extract ++: trigger daily job

loop for each data source
  Extract -> Extract: fetchFromSource(config)
  Extract ->> RawQ: enqueue(rawRecord)
end
deactivate Extract

|||

loop process raw records
  RawQ ->> Transform ++: dequeue(rawRecord)
  Transform -> Transform: validate()
  Transform -> Transform: normalize()
  Transform -> Transform: enrich()

  alt valid record
    Transform ->> ProcQ: enqueue(processedRecord)
  else invalid record
    Transform -> Transform: logError()
  end
  deactivate Transform
end

|||

loop load processed records
  ProcQ ->> Load ++: dequeue(processedRecord)
  Load -> DW: upsert(record)
  DW --> Load: ok
  deactivate Load
end

Sched -> Sched: log completion

@enduml
```

## Combining Patterns

Complex systems often combine multiple patterns. For example, an e-commerce checkout might use:

1. **Auth Flow** (Pattern 1) for user authentication
2. **CRUD** (Pattern 2) for cart management
3. **Saga** (Pattern 4) for distributed order processing
4. **Event-Driven** (Pattern 3) for post-order notifications
5. **Circuit Breaker** (Pattern 5) for external payment provider calls

When combining, use dividers (`== Phase Name ==`) to separate the patterns and keep each section focused on one concern.
