# Architecture Documentation Patterns

Reusable PlantUML snippets for common architecture patterns.
Each pattern is a starting point; adapt participants, labels, and
structure to your specific system.

## Microservice Choreography

Async messages between services via message queue.

```plantuml
@startuml
participant "Order Service" as OS
queue "Message Broker" as Q
participant "Inventory Service" as IS
participant "Notification Service" as NS

OS -> Q : publish OrderPlaced
Q -> IS : consume OrderPlaced
activate IS
IS -> IS : Reserve stock
IS -> Q : publish StockReserved
deactivate IS
Q -> NS : consume StockReserved
activate NS
NS -> NS : Send confirmation email
deactivate NS
@enduml
```

## Authentication Flow (OAuth2/JWT)

Token-based auth with refresh flow.

```plantuml
@startuml
actor User
participant "Client App" as App
participant "Auth Server" as Auth
database "Token Store" as TS

User -> App : Login (credentials)
App -> Auth ++ : POST /oauth/token\n(grant_type=password)
Auth -> Auth : Validate credentials
Auth -> TS : Store refresh token
Auth --> App -- : { access_token, refresh_token, expires_in }
App --> User : Authenticated

== Token Refresh ==

App -> Auth ++ : POST /oauth/token\n(grant_type=refresh_token)
Auth -> TS : Validate refresh token
Auth -> TS : Rotate refresh token
Auth --> App -- : { new_access_token, new_refresh_token }
@enduml
```

## REST CRUD API

Controller to service to repository to database layering.

```plantuml
@startuml
participant "API Client" as C
box "Application" #F0F7FC
  participant "Controller" as Ctrl
  participant "Service" as Svc
  participant "Repository" as Repo
end box
database "Database" as DB

C -> Ctrl ++ : POST /api/resources
Ctrl -> Svc ++ : create(dto)
Svc -> Svc : Validate business rules
Svc -> Repo ++ : save(entity)
Repo -> DB : INSERT INTO resources
DB --> Repo : OK
Repo --> Svc -- : savedEntity
Svc --> Ctrl -- : responseDto
Ctrl --> C -- : 201 Created + Location header
@enduml
```

## Event-Driven Architecture

Producer publishes events to a bus consumed by multiple subscribers.

```plantuml
@startuml
participant "Producer" as P
queue "Event Bus" as EB
participant "Consumer A" as CA
participant "Consumer B" as CB
database "Event Store" as ES

P -> EB : emit DomainEvent
EB -> ES : persist event
EB -> CA : deliver DomainEvent
activate CA
CA -> CA : Handle event
CA --> EB : ack
deactivate CA
EB -> CB : deliver DomainEvent
activate CB
CB -> CB : Handle event
CB --> EB : ack
deactivate CB
@enduml
```

## Saga Pattern

Distributed transaction with compensating actions on failure.

```plantuml
@startuml
participant "Saga Orchestrator" as SO
participant "Order Service" as OS
participant "Payment Service" as PS
participant "Shipping Service" as SS

SO -> OS ++ : CreateOrder
OS --> SO -- : OrderCreated

SO -> PS ++ : ProcessPayment
PS --> SO -- : PaymentConfirmed

SO -> SS ++ : ArrangeShipping
SS --> SO -- : ShippingFailed

== Compensating Actions ==

SO -> PS ++ : RefundPayment
PS --> SO -- : PaymentRefunded

SO -> OS ++ : CancelOrder
OS --> SO -- : OrderCancelled
@enduml
```

## Circuit Breaker

State machine for closed, open, and half-open states.

```plantuml
@startuml
hide empty description

state "Closed" as C : Requests pass through\nFailure counter tracked
state "Open" as O : Requests fail fast\nTimer running
state "Half-Open" as HO : Limited trial requests\nTest downstream health

[*] --> C

C --> O : Failure threshold\nexceeded
O --> HO : Timeout expired
HO --> C : Trial request\nsucceeded
HO --> O : Trial request\nfailed
C --> C : Success /\nreset counter
O --> O : Request arrives /\nfail fast
@enduml
```

## C4 System Context

Person interacting with a system that depends on external systems.

```plantuml
@startuml
!include <C4/C4_Context>

title System Context Diagram

Person(user, "Customer", "Uses the web application")

System(webapp, "Web Application", "Handles customer requests")

System_Ext(email, "Email Service", "Sends transactional emails")
System_Ext(payment, "Payment Gateway", "Processes payments")
System_Ext(identity, "Identity Provider", "OAuth2 / SSO")

Rel(user, webapp, "Browses", "HTTPS")
Rel(webapp, email, "Sends emails", "SMTP/API")
Rel(webapp, payment, "Processes payments", "HTTPS/REST")
Rel(webapp, identity, "Authenticates via", "OAuth2")
@enduml
```
