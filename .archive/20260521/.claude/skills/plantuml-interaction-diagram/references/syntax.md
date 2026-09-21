# PlantUML Sequence Diagram Syntax Reference

Complete syntax reference for PlantUML sequence/interaction diagrams. Consult this file during diagram generation when specific syntax is needed.

## Document Structure

Every sequence diagram is wrapped in start/end markers:

```plantuml
@startuml diagram-name
' diagram content here
@enduml
```

Multiple diagrams can exist in one file using separate `@startuml`/`@enduml` blocks.

## Participant Types and Declaration

### Basic Declaration

```plantuml
participant "Display Name" as alias
participant alias
```

### All Participant Types

```plantuml
actor       "End User"              as User
participant "Generic Service"       as Svc
boundary    "API Gateway"           as GW
control     "Orchestrator"          as Orch
entity      "Order Entity"          as Order
database    "PostgreSQL"            as DB
collections "Worker Pool"           as Workers
queue       "Message Queue"         as MQ
```

### Participant Ordering

Participants appear left-to-right in the order they are declared. Declare them in the desired visual order before any messages.

### Participant Styling

```plantuml
participant Alice #LightBlue
participant Bob #FF9999
participant "Service" as Svc <<Stereotype>>
```

### Create and Destroy

```plantuml
create Worker
Alice -> Worker: new
Worker -> Worker: process
destroy Worker
```

## Arrow Types

### Solid Arrows (Synchronous)

| Syntax | Description |
|--------|-------------|
| `->` | Solid line, solid arrowhead (standard sync call) |
| `->>` | Solid line, thin arrowhead |
| `->o` | Solid line, open circle (lost message) |
| `->x` | Solid line, cross (message destruction) |

### Dotted Arrows (Asynchronous / Return)

| Syntax | Description |
|--------|-------------|
| `-->` | Dotted line, solid arrowhead (return / async) |
| `-->>` | Dotted line, thin arrowhead |
| `-->o` | Dotted line, open circle |
| `-->x` | Dotted line, cross |

### Bidirectional and Self

| Syntax | Description |
|--------|-------------|
| `<->` | Bidirectional solid |
| `<-->` | Bidirectional dotted |
| `Alice -> Alice` | Self-message (loopback) |

### Colored Arrows

```plantuml
Alice -[#red]> Bob: urgent message
Alice -[#0000FF]-> Bob: blue return
```

## Message Labels

Messages carry labels after the colon:

```plantuml
Alice -> Bob: POST /api/users
Bob --> Alice: 201 Created
Alice -> Alice: validateInput()
```

### Creole Formatting in Labels

```plantuml
Alice -> Bob: **bold message**
Alice -> Bob: //italic message//
Alice -> Bob: ""monospaced""
Alice -> Bob: <color:red>red text</color>
Alice -> Bob: <back:yellow>highlighted</back>
```

## Activation / Lifeline

### Explicit Activation

```plantuml
Alice -> Bob: request
activate Bob
Bob -> DB: query
activate DB
DB --> Bob: result
deactivate DB
Bob --> Alice: response
deactivate Bob
```

### Shorthand Activation

```plantuml
Alice -> Bob ++: request          ' activate Bob
Bob -> DB ++: query               ' activate DB
DB --> Bob --: result             ' deactivate DB
Bob --> Alice --: response        ' deactivate Bob
```

### Colored Activation

```plantuml
Alice -> Bob ++ #FF0000: urgent request
Bob --> Alice --: done
```

### Nested Activation

```plantuml
Alice -> Bob ++: first call
Alice -> Bob ++: second call      ' Stacked activation bar
Bob --> Alice --: second response
Bob --> Alice --: first response
```

### Return Shorthand

```plantuml
Alice -> Bob ++: request
return response                   ' Automatically deactivates Bob and returns to Alice
```

## Fragments (Combined Fragments)

### alt / else (Conditional)

```plantuml
alt successful case
  Alice -> Bob: request
  Bob --> Alice: 200 OK
else failure case
  Alice -> Bob: request
  Bob --> Alice: 500 Error
end
```

Multiple else branches:

```plantuml
alt condition A
  Alice -> Bob: path A
else condition B
  Alice -> Bob: path B
else condition C
  Alice -> Bob: path C
end
```

### opt (Optional)

```plantuml
opt MFA enabled
  Auth -> User: request MFA code
  User -> Auth: provide MFA code
  Auth -> Auth: validate MFA
end
```

### loop (Iteration)

```plantuml
loop for each item in cart
  Cart -> Inventory: checkStock(item)
  Inventory --> Cart: stockLevel
end
```

### par (Parallel)

```plantuml
par send notifications
  Service -> Email: sendEmail()
and
  Service -> SMS: sendSMS()
and
  Service -> Push: sendPush()
end
```

### break (Early Termination)

```plantuml
Alice -> Bob: request
break rate limit exceeded
  Bob --> Alice: 429 Too Many Requests
end
Bob -> DB: query
```

### critical (Atomic Section)

```plantuml
critical database transaction
  Service -> DB: BEGIN
  Service -> DB: UPDATE accounts
  Service -> DB: UPDATE ledger
  Service -> DB: COMMIT
end
```

### group (Custom Label)

```plantuml
group Phase 1: Validation [retry up to 3 times]
  Client -> Server: validate(data)
  Server --> Client: result
end
```

### neg (Negative / Invalid)

```plantuml
neg invalid input
  Client -> Server: malformed request
  Server --> Client: 400 Bad Request
end
```

### assert (Assertion)

```plantuml
assert user is authenticated
  Client -> API: request with valid token
  API --> Client: 200 OK
end
```

## Notes

### Positioned Notes

```plantuml
note left of Alice: This is a note
note right of Bob: Another note
note over Alice: Note over Alice
note over Alice, Bob: Note spanning participants
```

### Multi-line Notes

```plantuml
note right of Alice
  This is a
  multi-line note
end note
```

### Note Shapes

```plantuml
hnote over Alice: hexagonal note
rnote over Bob: rectangular note
```

### Colored Notes

```plantuml
note over Alice #FFAAAA: Warning note
note over Bob #LightGreen: Success note
```

## Layout and Spacing

### Box Grouping

```plantuml
box "Frontend" #LightBlue
  actor User
  participant "Web App" as Web
end box

box "Backend" #LightGreen
  participant "API" as API
  participant "Service" as Svc
end box

box "Data Layer" #LightYellow
  database "DB" as DB
  queue "Queue" as Q
end box
```

### Dividers

```plantuml
== Initialization ==
Alice -> Bob: setup()
== Processing ==
Alice -> Bob: process()
== Cleanup ==
Alice -> Bob: teardown()
```

### Spacing

```plantuml
Alice -> Bob: message1
|||                        ' Small spacing
Alice -> Bob: message2
||45||                     ' 45 pixel spacing
Alice -> Bob: message3
```

### Delays

```plantuml
Alice -> Bob: request
...                        ' Ordinary delay
Alice -> Bob: another
... 5 minutes later ...    ' Labeled delay
Alice -> Bob: yet another
```

### Page Breaks

```plantuml
Alice -> Bob: message on page 1
newpage
Alice -> Bob: message on page 2
newpage A title for page 3
Alice -> Bob: message on page 3
```

## Reference Blocks

```plantuml
ref over Alice, Bob
  See authentication
  flow diagram
end ref
```

Or single-line:

```plantuml
ref over Alice, Bob: See auth diagram
```

## Autonumber

### Basic Numbering

```plantuml
autonumber
Alice -> Bob: first        ' 1
Bob -> Carol: second       ' 2
Carol --> Bob: third       ' 3
```

### Custom Start and Increment

```plantuml
autonumber 10 5
Alice -> Bob: message      ' 10
Bob -> Carol: message      ' 15
```

### Formatted Numbering

```plantuml
autonumber "<b>[000]"
Alice -> Bob: message      ' [001]
Bob -> Carol: message      ' [002]
```

### Stop and Resume

```plantuml
autonumber
Alice -> Bob: numbered     ' 1
autonumber stop
Bob -> Carol: not numbered
autonumber resume
Carol -> Alice: numbered   ' 2
```

## Titles, Headers, Footers

```plantuml
title Main Title
header Page Header
footer Page %page% of %lastpage%
caption Figure 1: System Overview
```

## Skinparam (Styling)

### Sequence-Specific Parameters

```plantuml
skinparam sequence {
  ArrowColor #333333
  ArrowFontSize 12
  LifeLineBorderColor #333333
  LifeLineBackgroundColor #FFFFFF
  ParticipantBorderColor #333333
  ParticipantBackgroundColor #FEFECE
  ParticipantFontSize 14
  ParticipantFontColor #333333
  ActorBorderColor #333333
  ActorBackgroundColor #FEFECE
  DatabaseBackgroundColor #E8F5E9
  QueueBackgroundColor #E3F2FD
  BoxBorderColor #999999
  BoxBackgroundColor #F5F5F5
  DividerBackgroundColor #EEEEEE
  GroupBackgroundColor #F0F0F0
}
```

### Global Parameters

```plantuml
skinparam backgroundColor #FFFFFF
skinparam shadowing false
skinparam handwritten false
skinparam defaultFontName "Segoe UI"
skinparam defaultFontSize 12
skinparam noteBorderColor #999999
skinparam noteBackgroundColor #FFFFCC
skinparam roundcorner 5
```

### Themes

```plantuml
!theme plain
!theme cerulean
!theme superhero
!theme minty
```

`!theme plain` is recommended as the default for clean, professional diagrams.

## Preprocessing

### Variables

```plantuml
!$api_url = "https://api.example.com"
Alice -> Bob: GET $api_url/users
```

### Includes

```plantuml
!include common-participants.puml
!include styles.puml
```

### Conditionals

```plantuml
!$show_mfa = %true()
!if ($show_mfa)
  Auth -> User: request MFA
  User -> Auth: provide code
!endif
```

## Comments

```plantuml
' Single-line comment
/' Multi-line
   comment '/
```
