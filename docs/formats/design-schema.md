# Design schema

_This document is auto-generated from `DesignDocument.model_json_schema()`._

```json
{
  "$defs": {
    "DesignMeta": {
      "additionalProperties": false,
      "properties": {
        "content_hash": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Content Hash"
        },
        "created": {
          "format": "date-time",
          "title": "Created",
          "type": "string"
        },
        "modified": {
          "format": "date-time",
          "title": "Modified",
          "type": "string"
        },
        "name": {
          "title": "Name",
          "type": "string"
        },
        "parent_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Parent Id"
        },
        "version_id": {
          "title": "Version Id",
          "type": "string"
        }
      },
      "required": [
        "name",
        "version_id",
        "created",
        "modified"
      ],
      "title": "DesignMeta",
      "type": "object"
    },
    "Feature": {
      "additionalProperties": false,
      "properties": {
        "feed_holes": {
          "items": {
            "type": "string"
          },
          "title": "Feed Holes",
          "type": "array"
        },
        "host_panels": {
          "items": {
            "type": "string"
          },
          "title": "Host Panels",
          "type": "array"
        },
        "notes": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Notes"
        },
        "tapes": {
          "items": {
            "type": "string"
          },
          "title": "Tapes",
          "type": "array"
        },
        "type": {
          "enum": [
            "ram_air_pod",
            "tubular_appendage",
            "applique",
            "vent",
            "hole"
          ],
          "title": "Type",
          "type": "string"
        }
      },
      "required": [
        "type",
        "host_panels"
      ],
      "title": "Feature",
      "type": "object"
    },
    "GoreSpec": {
      "additionalProperties": false,
      "properties": {
        "count": {
          "minimum": 3,
          "title": "Count",
          "type": "integer"
        },
        "crown_ring": {
          "exclusiveMinimum": 0,
          "title": "Crown Ring",
          "type": "number"
        },
        "meridian_profile_control_points": {
          "items": {
            "$ref": "#/$defs/MeridianControlPoint"
          },
          "title": "Meridian Profile Control Points",
          "type": "array"
        },
        "mouth_diameter": {
          "exclusiveMinimum": 0,
          "title": "Mouth Diameter",
          "type": "number"
        },
        "panel_rows": {
          "items": {
            "$ref": "#/$defs/PanelRow"
          },
          "title": "Panel Rows",
          "type": "array"
        },
        "parachute": {
          "anyOf": [
            {
              "$ref": "#/$defs/ParachuteSpec"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "parachute_hole_diameter": {
          "exclusiveMinimum": 0,
          "title": "Parachute Hole Diameter",
          "type": "number"
        },
        "seal_overlap": {
          "minimum": 0,
          "title": "Seal Overlap",
          "type": "number"
        }
      },
      "required": [
        "count",
        "meridian_profile_control_points",
        "panel_rows",
        "mouth_diameter",
        "crown_ring",
        "parachute_hole_diameter",
        "seal_overlap"
      ],
      "title": "GoreSpec",
      "type": "object"
    },
    "MeridianControlPoint": {
      "additionalProperties": false,
      "properties": {
        "x": {
          "title": "X",
          "type": "number"
        },
        "y": {
          "title": "Y",
          "type": "number"
        }
      },
      "required": [
        "x",
        "y"
      ],
      "title": "MeridianControlPoint",
      "type": "object"
    },
    "OperatingConditions": {
      "additionalProperties": false,
      "properties": {
        "altitude": {
          "title": "Altitude",
          "type": "number"
        },
        "ambient_pressure": {
          "exclusiveMinimum": 0,
          "title": "Ambient Pressure",
          "type": "number"
        },
        "ambient_temperature": {
          "title": "Ambient Temperature",
          "type": "number"
        },
        "internal_temperature": {
          "title": "Internal Temperature",
          "type": "number"
        },
        "payload_mass": {
          "minimum": 0,
          "title": "Payload Mass",
          "type": "number"
        }
      },
      "required": [
        "ambient_temperature",
        "ambient_pressure",
        "altitude",
        "internal_temperature",
        "payload_mass"
      ],
      "title": "OperatingConditions",
      "type": "object"
    },
    "PanelRow": {
      "additionalProperties": false,
      "properties": {
        "finished_height": {
          "exclusiveMinimum": 0,
          "title": "Finished Height",
          "type": "number"
        },
        "letter": {
          "maxLength": 4,
          "minLength": 1,
          "title": "Letter",
          "type": "string"
        }
      },
      "required": [
        "letter",
        "finished_height"
      ],
      "title": "PanelRow",
      "type": "object"
    },
    "ParachuteSpec": {
      "additionalProperties": false,
      "description": "Flat parachute closing the crown hole (theory: docs/theory/parachute-geometry.md).\n\nAttributes\n----------\ngore_count : int\n    Number of parachute gores (>= 3), usually the envelope gore count.\ndiameter : float\n    Finished flat diameter, m; normally the hole diameter plus twice the seal overlap.\ncentre_diameter : float\n    Finished diameter of the centre disc the gores are sewn to, m.",
      "properties": {
        "centre_diameter": {
          "exclusiveMinimum": 0,
          "title": "Centre Diameter",
          "type": "number"
        },
        "diameter": {
          "exclusiveMinimum": 0,
          "title": "Diameter",
          "type": "number"
        },
        "gore_count": {
          "minimum": 3,
          "title": "Gore Count",
          "type": "integer"
        }
      },
      "required": [
        "gore_count",
        "diameter",
        "centre_diameter"
      ],
      "title": "ParachuteSpec",
      "type": "object"
    },
    "RiggingSpec": {
      "additionalProperties": false,
      "properties": {
        "crown_line": {
          "title": "Crown Line",
          "type": "string"
        },
        "flying_wires": {
          "items": {
            "type": "string"
          },
          "title": "Flying Wires",
          "type": "array"
        },
        "parachute_confluence_centering": {
          "title": "Parachute Confluence Centering",
          "type": "string"
        },
        "red_line": {
          "title": "Red Line",
          "type": "string"
        }
      },
      "required": [
        "crown_line",
        "red_line",
        "flying_wires",
        "parachute_confluence_centering"
      ],
      "title": "RiggingSpec",
      "type": "object"
    },
    "ScaleVariant": {
      "additionalProperties": false,
      "properties": {
        "factor_k": {
          "exclusiveMinimum": 0,
          "title": "Factor K",
          "type": "number"
        },
        "fixed_size_overrides": {
          "additionalProperties": {
            "type": "number"
          },
          "title": "Fixed Size Overrides",
          "type": "object"
        },
        "model_fabric_override": {
          "additionalProperties": {
            "type": "string"
          },
          "title": "Model Fabric Override",
          "type": "object"
        }
      },
      "required": [
        "factor_k"
      ],
      "title": "ScaleVariant",
      "type": "object"
    },
    "SeamCurve": {
      "additionalProperties": false,
      "properties": {
        "panel_a": {
          "title": "Panel A",
          "type": "string"
        },
        "panel_b": {
          "title": "Panel B",
          "type": "string"
        },
        "points": {
          "items": {
            "$ref": "#/$defs/MeridianControlPoint"
          },
          "title": "Points",
          "type": "array"
        }
      },
      "required": [
        "panel_a",
        "panel_b",
        "points"
      ],
      "title": "SeamCurve",
      "type": "object"
    },
    "SeamType": {
      "additionalProperties": false,
      "properties": {
        "allowance": {
          "minimum": 0,
          "title": "Allowance",
          "type": "number"
        },
        "efficiency": {
          "exclusiveMinimum": 0,
          "maximum": 1,
          "title": "Efficiency",
          "type": "number"
        },
        "name": {
          "title": "Name",
          "type": "string"
        },
        "rows_of_stitching": {
          "minimum": 1,
          "title": "Rows Of Stitching",
          "type": "integer"
        }
      },
      "required": [
        "name",
        "allowance",
        "rows_of_stitching",
        "efficiency"
      ],
      "title": "SeamType",
      "type": "object"
    },
    "SpecialSpec": {
      "additionalProperties": false,
      "properties": {
        "mesh_reference": {
          "title": "Mesh Reference",
          "type": "string"
        },
        "panel_list": {
          "items": {
            "type": "string"
          },
          "title": "Panel List",
          "type": "array"
        },
        "seam_curves": {
          "items": {
            "$ref": "#/$defs/SeamCurve"
          },
          "title": "Seam Curves",
          "type": "array"
        }
      },
      "required": [
        "mesh_reference",
        "seam_curves",
        "panel_list"
      ],
      "title": "SpecialSpec",
      "type": "object"
    },
    "TapeSet": {
      "additionalProperties": false,
      "properties": {
        "hole": {
          "$ref": "#/$defs/TapeSpec"
        },
        "horizontal": {
          "$ref": "#/$defs/TapeSpec"
        },
        "rim": {
          "$ref": "#/$defs/TapeSpec"
        },
        "vertical": {
          "$ref": "#/$defs/TapeSpec"
        }
      },
      "required": [
        "vertical",
        "horizontal",
        "rim",
        "hole"
      ],
      "title": "TapeSet",
      "type": "object"
    },
    "TapeSpec": {
      "additionalProperties": false,
      "properties": {
        "class": {
          "title": "Class",
          "type": "string"
        },
        "strength": {
          "exclusiveMinimum": 0,
          "title": "Strength",
          "type": "number"
        },
        "width": {
          "exclusiveMinimum": 0,
          "title": "Width",
          "type": "number"
        }
      },
      "required": [
        "class",
        "width",
        "strength"
      ],
      "title": "TapeSpec",
      "type": "object"
    }
  },
  "additionalProperties": false,
  "properties": {
    "envelope_type": {
      "enum": [
        "gore",
        "special"
      ],
      "title": "Envelope Type",
      "type": "string"
    },
    "features": {
      "items": {
        "$ref": "#/$defs/Feature"
      },
      "title": "Features",
      "type": "array"
    },
    "gores": {
      "anyOf": [
        {
          "$ref": "#/$defs/GoreSpec"
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "meta": {
      "$ref": "#/$defs/DesignMeta"
    },
    "operating": {
      "$ref": "#/$defs/OperatingConditions"
    },
    "rigging": {
      "$ref": "#/$defs/RiggingSpec"
    },
    "scale_variants": {
      "items": {
        "$ref": "#/$defs/ScaleVariant"
      },
      "title": "Scale Variants",
      "type": "array"
    },
    "schema_version": {
      "default": 2,
      "title": "Schema Version",
      "type": "integer"
    },
    "seam_types": {
      "items": {
        "$ref": "#/$defs/SeamType"
      },
      "title": "Seam Types",
      "type": "array"
    },
    "special": {
      "anyOf": [
        {
          "$ref": "#/$defs/SpecialSpec"
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "tapes": {
      "$ref": "#/$defs/TapeSet"
    },
    "zones": {
      "additionalProperties": {
        "type": "string"
      },
      "title": "Zones",
      "type": "object"
    }
  },
  "required": [
    "meta",
    "envelope_type",
    "zones",
    "tapes",
    "seam_types",
    "operating",
    "rigging"
  ],
  "title": "DesignDocument",
  "type": "object"
}
```
