# Component Diagram Syntax Reference

PlantUML component diagrams visualize the organization and relationships of system
components, their interfaces, and interdependencies. Source: PlantUML Language
Reference Guide, Chapter 7.

## Element Types

### Components

```plantuml
[First Component]
[Another Component] as Comp2
component Comp3
component [Last\ncomponent] as Comp4
```

Long descriptions with brackets:

```plantuml
component comp1 [
  This component
  has a long comment
  on several lines
]
```

### Interfaces

```plantuml
() "First Interface"
() "Another Interface" as Interf2
interface Interf3
interface "Last\ninterface" as Interf4
```

### Ports

```plantuml
component Server {
  port p1
  portin p2
  portout p3
  component inner
}
```

- `port` -- bidirectional
- `portin` -- input only
- `portout` -- output only

## Relationships

Links use combinations of dotted (`..`), straight (`--`), and arrow (`-->`) symbols:

```plantuml
DataAccess - [First Component]
[First Component] ..> HTTP : use
[Component] --> Interface1
```

### Arrow Types

| Syntax | Meaning              |
|--------|----------------------|
| `--`   | Solid line           |
| `..`   | Dotted line          |
| `-->`  | Solid arrow          |
| `..>`  | Dotted arrow         |
| `-`    | Horizontal solid     |
| `.`    | Horizontal dotted    |

### Arrow Direction

```plantuml
[Component] -left-> left
[Component] -right-> right
[Component] -up-> up
[Component] -down-> down
```

Shorten to `-l->`, `-r->`, `-u->`, `-d->`.

### Arrow Styling

```plantuml
A -[bold]-> B
A -[dashed]-> C
A -[#red]-> D : red arrow
A -[#green,dashed,thickness=2]-> E
```

Inline: `A --> B #line:red;line.bold;text:red : label`

## Grouping and Layout

### Container Keywords

```plantuml
package "Some Group" {
  HTTP - [First Component]
  [Another Component]
}
node "Other Groups" {
  FTP - [Second Component]
}
cloud {
  [Example 1]
}
database "MySql" {
  folder "This is my folder" {
    [Folder 3]
  }
  frame "Foo" {
    [Frame 4]
  }
}
```

Available grouping keywords: `package`, `node`, `folder`, `frame`, `cloud`, `database`.

### Diagram Orientation

```plantuml
left to right direction
```

### Hide Unlinked

```plantuml
hide @unlinked
' or
remove @unlinked
```

### Tags for Show/Hide

```plantuml
component C1 $tag1
component C2
remove $tag1
```

## Styling

### Skinparam

```plantuml
skinparam interface {
  backgroundColor RosyBrown
  borderColor orange
}
skinparam component {
  FontSize 13
  BackgroundColor<<Apache>> Pink
  BorderColor<<Apache>> #FF6655
  BackgroundColor gold
  ArrowColor #FF6655
}
```

### Component Style Variants

```plantuml
skinparam componentStyle uml2       ' default, shows component icon
skinparam componentStyle uml1       ' UML1 notation
skinparam componentStyle rectangle  ' plain rectangles, no UML icon
```

### Inline Element Color

```plantuml
component [Web Server] #Yellow
cloud c #pink;line:red;line.bold;text:red
```

### Notes

```plantuml
note top of [Component] : A top note
note right of [First Component]
  A note on several lines
end note
note "Floating note" as N1
[Component] .. N1
```

### Sprites in Stereotypes

```plantuml
sprite $svc [16x16/16] {
  FFFFFFFFFFFFFFFF
  ...
}
rectangle "Service" <<$svc>>
```

## C4 Model Macros

PlantUML supports C4 architecture diagrams via stdlib includes. These provide
high-level abstractions for system context, container, and component views.

### Include Statements

```plantuml
!include <C4/C4_Context>
!include <C4/C4_Container>
!include <C4/C4_Component>
```

### C4 Context Elements

```plantuml
Person(alias, "Label", "Description")
Person_Ext(alias, "Label", "Description")
System(alias, "Label", "Description")
System_Ext(alias, "Label", "Description")
System_Boundary(alias, "Label") {
  ' nested elements
}
Enterprise_Boundary(alias, "Label") {
  ' nested elements
}
```

### C4 Container Elements

```plantuml
Container(alias, "Label", "Technology", "Description")
ContainerDb(alias, "Label", "Technology", "Description")
ContainerQueue(alias, "Label", "Technology", "Description")
Container_Ext(alias, "Label", "Technology", "Description")
Container_Boundary(alias, "Label") {
  ' nested elements
}
```

### C4 Component Elements

```plantuml
Component(alias, "Label", "Technology", "Description")
ComponentDb(alias, "Label", "Technology", "Description")
ComponentQueue(alias, "Label", "Technology", "Description")
Component_Ext(alias, "Label", "Technology", "Description")
```

### C4 Relationships

```plantuml
Rel(from, to, "Label")
Rel(from, to, "Label", "Technology")
Rel_D(from, to, "Label")          ' downward
Rel_U(from, to, "Label")          ' upward
Rel_L(from, to, "Label")          ' left
Rel_R(from, to, "Label")          ' right
Rel_Back(from, to, "Label")
BiRel(from, to, "Label")
```

### C4 Layout Helpers

```plantuml
LAYOUT_WITH_LEGEND()
LAYOUT_TOP_DOWN()
LAYOUT_LEFT_RIGHT()
LAYOUT_AS_SKETCH()
```

## Example

### Standard Component Diagram

```plantuml
@startuml
skinparam componentStyle rectangle

package "Web Tier" {
  [Load Balancer] as LB
  [Web Server] as WS
}

package "Application Tier" {
  [API Gateway] as GW
  [Auth Service] as Auth
  [Order Service] as Orders
  [Notification Service] as Notif
}

package "Data Tier" {
  database "PostgreSQL" as DB
  database "Redis Cache" as Cache
  queue "Message Queue" as MQ
}

LB --> WS
WS --> GW
GW --> Auth : authenticate
GW --> Orders : process
Orders --> DB : persist
Orders --> Cache : cache reads
Orders ..> MQ : publish events
MQ ..> Notif : consume events
@enduml
```

### C4 Context Diagram

```plantuml
@startuml
!include <C4/C4_Context>

title System Context Diagram

Person(user, "Customer", "A user of the system")
System(sys, "E-Commerce Platform", "Allows customers to browse and purchase")
System_Ext(payment, "Payment Provider", "Handles payment processing")
System_Ext(email, "Email Service", "Sends transactional emails")

Rel(user, sys, "Browses and purchases", "HTTPS")
Rel(sys, payment, "Processes payments", "HTTPS/API")
Rel(sys, email, "Sends emails", "SMTP")

LAYOUT_WITH_LEGEND()
@enduml
```
