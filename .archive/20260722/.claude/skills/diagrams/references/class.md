# Class Diagram Syntax Reference

PlantUML class diagrams use a syntax that mirrors programming languages for intuitive
diagram creation. Source: PlantUML Language Reference Guide, Chapter 3.

## Element Types

### Declaring Elements

```plantuml
class ClassName
abstract class AbstractName
abstract AbstractName
interface InterfaceName
enum EnumName
annotation AnnotationName
entity EntityName
exception ExceptionName
struct StructName
```

Use `as` for aliases or quotes for names with spaces:

```plantuml
class "My Long Name" as MyClass
class MyClass as "Display Name"
```

### Attributes and Methods

Declare with `:` or group inside `{}`. Parentheses distinguish methods from fields:

```plantuml
class Example {
  String name
  int count
  void doWork()
  String getName()
}
```

Override parser with `{field}` and `{method}`:

```plantuml
class Overrides {
  {field} A field (despite parentheses)
  {method} Some method
}
```

### Visibility Modifiers

| Symbol | Meaning         |
|--------|-----------------|
| `+`    | public          |
| `-`    | private         |
| `#`    | protected       |
| `~`    | package private |

```plantuml
class Account {
  - balance : BigDecimal
  # owner : String
  ~ internalId : int
  + getBalance() : BigDecimal
}
```

### Static and Abstract Members

```plantuml
class Service {
  {static} String VERSION
  {abstract} void process()
}
```

### Separators in Class Body

Use `--`, `..`, `==`, or `__` to create sections (with optional titles):

```plantuml
class Organized {
  .. Getters ..
  + getName()
  + getId()
  __ private data __
  - password
}
```

### Enums and Interfaces

```plantuml
enum Status {
  ACTIVE
  INACTIVE
  PENDING
}

interface Repository {
  + findById(id) : Entity
  + save(entity) : void
}
```

### Extends and Implements Keywords

```plantuml
class ArrayList implements List
class ArrayList extends AbstractList
class Child extends ParentA, ParentB
```

## Relationships

| Syntax      | Type           | Meaning                              |
|-------------|----------------|--------------------------------------|
| `<\|--`     | Extension      | Inheritance (solid + triangle)       |
| `<\|..`     | Implementation | Realization (dotted + triangle)      |
| `*--`       | Composition    | Part cannot exist without the whole  |
| `o--`       | Aggregation    | Part can exist independently         |
| `-->`       | Dependency     | Uses (solid arrow)                   |
| `..>`       | Dependency     | Uses (dotted arrow)                  |
| `--`        | Association    | Plain line                           |
| `..`        | Association    | Dotted line                          |

### Labels and Cardinality

```plantuml
ClassA "1" *-- "many" ClassB : contains
Driver - Car : drives >
Car *- Wheel : has 4 >
```

### Arrow Direction

- `--` = vertical (two dashes)
- `-` = horizontal (one dash)
- Use `-left->`, `-right->`, `-up->`, `-down->` for explicit direction
- Shorten to `-l->`, `-r->`, `-u->`, `-d->`

### Arrow Styling

```plantuml
A -[bold]-> B
A -[dashed]-> C
A -[dotted]-> D
A -[#red]-> E : red arrow
A -[#green,dashed,thickness=2]-> F
```

Inline style: `A --> B #line:red;line.bold;text:red : label`

### Arrows Between Members

```plantuml
Foo::field1 --> Bar::field3 : links
```

### Association Classes

```plantuml
Student "0..*" - "1..*" Course
(Student, Course) .. Enrollment
```

## Grouping and Layout

### Packages

```plantuml
package "Domain Model" {
  class Entity
}
package com.example <<Folder>> {
  class Service
}
```

Package styles via stereotype: `<<Node>>`, `<<Rectangle>>`, `<<Folder>>`,
`<<Frame>>`, `<<Cloud>>`, `<<Database>>`

### Namespaces (Automatic)

```plantuml
set separator ::
class X1::X2::Foo {
  some info
}
```

Disable with `set separator none`.

### Together (Force Grouping)

```plantuml
together {
  class A
  class B
}
```

### Hidden Links (Force Layout)

```plantuml
A -[hidden]-> B
```

### Diagram Orientation

```plantuml
left to right direction
' or (default):
top to bottom direction
```

### Lollipop Interface

```plantuml
class Foo
bar ()- Foo
```

## Styling

### Skinparam

```plantuml
skinparam class {
  BackgroundColor PaleGreen
  ArrowColor SeaGreen
  BorderColor SpringGreen
}
skinparam classAttributeIconSize 0
```

### Stereotypes and Spots

```plantuml
class Config <<Singleton>>
class Controller <<(S,#FF7700) Service>>
```

### Inline Element Color

```plantuml
class Foo #palegreen;line:green;line.dashed;text:green
class Bar #back:lightblue;header:blue
```

### Hide/Show

```plantuml
hide empty members
hide methods
hide <<Serializable>> circle
show ClassName fields
hide private members
```

### Generics

```plantuml
class List<T> {
  + add(item : T)
}
class Map<K, V>
```

### Notes

```plantuml
note top of ClassName : Short note
note left of ClassName
  Multi-line
  note content
end note
note "Floating note" as N1
ClassName .. N1

' Note on a member:
note right of ClassName::methodName
  Explains this method
end note

' Note on a link:
A --> B
note on link : describes relationship
```

### Group Inheritance Arrows

```plantuml
skinparam groupInheritance 2
```

## Example

```plantuml
@startuml
skinparam class {
  BackgroundColor White
  BorderColor #333333
}

abstract class Vehicle {
  - make : String
  - model : String
  - year : int
  + start() : void
  + {abstract} calculateInsurance() : BigDecimal
}

class Car extends Vehicle {
  - numDoors : int
  + calculateInsurance() : BigDecimal
}

class Truck extends Vehicle {
  - payload : double
  + calculateInsurance() : BigDecimal
}

interface Insurable {
  + getPolicy() : Policy
  + isPolicyActive() : boolean
}

class Policy {
  - policyNumber : String
  - premium : BigDecimal
  - status : PolicyStatus
}

enum PolicyStatus {
  ACTIVE
  EXPIRED
  CANCELLED
}

Car ..|> Insurable
Truck ..|> Insurable
Insurable --> Policy : covered by
Policy --> PolicyStatus

package "Fleet Management" {
  class Fleet {
    + addVehicle(v : Vehicle)
    + getVehicles() : List<Vehicle>
  }
  Fleet "1" o-- "0..*" Vehicle : manages
}
@enduml
```
