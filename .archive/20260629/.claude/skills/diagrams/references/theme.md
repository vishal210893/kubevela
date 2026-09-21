# Guidewire Theme Reference

## Color Palette

| Variable          | Hex       | Usage                        |
|-------------------|-----------|------------------------------|
| `GW_DARK`         | `#003B5C` | Borders, titles, dark accents|
| `GW_PRIMARY`      | `#0072CE` | Primary borders, arrows      |
| `GW_ACCENT`       | `#4DA8DA` | Actor/database backgrounds   |
| `GW_LIGHT`        | `#B3D9F2` | Entity/participant backgrounds|
| `GW_BG`           | `#F0F7FC` | Diagram background, packages |
| `GW_TEXT`          | `#1A1A2E` | All body text                |
| `GW_NOTE_BG`      | `#E8F4FD` | Note background              |
| `GW_NOTE_BORDER`  | `#4DA8DA` | Note border                  |

## Including the Theme

Place the pragma and theme include near the top of your diagram, after `@startuml`:

```plantuml
@startuml
!pragma layout smetana
!include ../guidewire-theme.puml

' ... diagram content ...
@enduml
```

**CRITICAL**: Always add `!pragma layout smetana` immediately after `@startuml`.
This uses PlantUML's built-in Smetana layout engine (pure Java) so diagrams
render without Graphviz in online tools, CI pipelines, and containers.

The theme path is relative to the `.puml` file location. Adjust `../` depth
as needed based on your file's directory.

## What the Theme Provides

The theme sets global defaults via `skinparam` for:

- **Global**: background color, font (Segoe UI, 12pt), no shadows, rounded corners (8px)
- **Sequence diagrams**: arrow, lifeline, participant, actor, database, box colors
- **Class diagrams**: background, border, header, attribute colors
- **Component/Package/Interface**: border and background colors
- **Deployment**: node, artifact, cloud, frame, folder, database, queue, storage
- **State diagrams**: background, border, start/end markers
- **Activity diagrams**: bar, diamond, swimlane, partition colors
- **Use case diagrams**: actor, rectangle, stereotype colors
- **ER entities**: background, border, font colors
- **Notes and legends**: background, border, font colors
- **Arrows and stereotypes**: default colors

## C4 Style Overrides

The theme auto-detects C4 libraries and applies Guidewire element
style overrides automatically. Just include the C4 library **before**
the theme -- do NOT add `UpdateElementStyle` calls in individual diagrams:

```plantuml
@startuml
!pragma layout smetana
!include <C4/C4_Context>
!include ../guidewire-theme.puml

' C4 Guidewire overrides are applied automatically by the theme.
' ... diagram content ...
@enduml
```

## Custom Override Block

To override theme defaults for a specific diagram, add a delimited
section after the theme include:

```plantuml
@startuml
!pragma layout smetana
!include ../guidewire-theme.puml

' ---- Custom Overrides ----
skinparam BackgroundColor white
skinparam sequence {
  ParticipantBackgroundColor #E8F4FD
  ArrowColor #003B5C
}
' ---- End Custom Overrides ----

' ... diagram content ...
@enduml
```

Place overrides between comment delimiters so they are easy to find
and maintain. Overrides must come **after** the theme include to
take precedence.

## Skinparam Customization Guide

### Per-Diagram-Type Blocks

```plantuml
skinparam sequence {
  ArrowColor #003B5C
  ParticipantBackgroundColor #E8F4FD
}

skinparam class {
  BackgroundColor #B3D9F2
  HeaderBackgroundColor #0072CE
  HeaderFontColor #FFFFFF
}

skinparam state {
  BackgroundColor #B3D9F2
  BorderColor #0072CE
}
```

### Global Properties

```plantuml
skinparam BackgroundColor #F0F7FC
skinparam defaultFontName "Segoe UI"
skinparam defaultFontSize 12
skinparam defaultFontColor #1A1A2E
skinparam shadowing false
skinparam roundCorner 8
```

### Arrow Styling

```plantuml
skinparam ArrowColor #0072CE
skinparam ArrowFontColor #1A1A2E
skinparam sequenceArrowThickness 2
```

### Element-Specific Overrides

Target specific element types:

```plantuml
skinparam entity {
  BackgroundColor #B3D9F2
  BorderColor #003B5C
}

skinparam database {
  BackgroundColor #4DA8DA
  BorderColor #003B5C
}

skinparam note {
  BackgroundColor #E8F4FD
  BorderColor #4DA8DA
}
```

### Style Block (Modern Syntax)

PlantUML also supports `<style>` blocks for more granular control:

```plantuml
<style>
  root {
    shadowing 0
    BackgroundColor #F0F7FC
  }
  arrow {
    LineColor #0072CE
    FontColor #1A1A2E
  }
</style>
```

## Quick Copy Palette

For use in raw diagrams without the theme file:

```plantuml
!define GW_DARK    #003B5C
!define GW_PRIMARY #0072CE
!define GW_ACCENT  #4DA8DA
!define GW_LIGHT   #B3D9F2
!define GW_BG      #F0F7FC
!define GW_TEXT    #1A1A2E
!define GW_NOTE_BG #E8F4FD
!define GW_NOTE_BORDER #4DA8DA
```
