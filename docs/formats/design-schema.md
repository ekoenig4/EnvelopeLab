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
    "FlyingWireSpec": {
      "additionalProperties": false,
      "description": "Flying wires from the mouth load tapes to the basket's burner frame.\n\nThe load tapes are gathered in equal groups; each group meets at a carabiner (crow's\nfoot) ``crows_foot_drop`` below the mouth, and one flying wire runs from each\ncarabiner to the nearest frame attachment point.\n\nAttributes\n----------\ncount : int\n    Flying wires, >= 3; the gore count must be a multiple.\nframe_points : int\n    Attachment points on the burner frame (4 for a square frame).\nframe_radius : float\n    Horizontal distance of the frame attachment points from the envelope axis, m.\nframe_drop : float\n    Height of the mouth above the frame attachment points, m.\nframe_azimuth_deg : float\n    Azimuth of the first frame point from seam N (degrees, boundary format).\ncrows_foot_drop : float\n    Height of the mouth above the carabiners, m (0: tapes end at the mouth).\nwire : LineSpec\n    Cable class.",
      "properties": {
        "count": {
          "minimum": 3,
          "title": "Count",
          "type": "integer"
        },
        "crows_foot_drop": {
          "minimum": 0.0,
          "title": "Crows Foot Drop",
          "type": "number"
        },
        "frame_azimuth_deg": {
          "default": 45.0,
          "title": "Frame Azimuth Deg",
          "type": "number"
        },
        "frame_drop": {
          "exclusiveMinimum": 0.0,
          "title": "Frame Drop",
          "type": "number"
        },
        "frame_points": {
          "default": 4,
          "minimum": 1,
          "title": "Frame Points",
          "type": "integer"
        },
        "frame_radius": {
          "minimum": 0.0,
          "title": "Frame Radius",
          "type": "number"
        },
        "wire": {
          "$ref": "#/$defs/LineSpec"
        }
      },
      "required": [
        "count",
        "frame_radius",
        "frame_drop",
        "crows_foot_drop",
        "wire"
      ],
      "title": "FlyingWireSpec",
      "type": "object"
    },
    "GoreSpec": {
      "additionalProperties": false,
      "description": "Standard-gore envelope: meridian, gores, panel rows and openings (m).\n\n``loft`` sets the lobe bulge of every gore (:class:`LoftPoint`), interpolated linearly\nbetween stations and constant beyond the first and last; ``None`` is the small-bulge\ngore (ratio 1 everywhere).",
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
        "loft": {
          "anyOf": [
            {
              "items": {
                "$ref": "#/$defs/LoftPoint"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Loft"
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
    "LineSpec": {
      "additionalProperties": false,
      "description": "A line or cable class (shroud, centralising, red line, flying wire, control line).\n\nAttributes\n----------\nline_class : str\n    Name of the line class (alias ``class``).\nstrength : TaggedValue\n    Minimum breaking strength, N.\nlinear_mass : TaggedValue\n    Mass per length, kg/m.",
      "properties": {
        "class": {
          "title": "Class",
          "type": "string"
        },
        "linear_mass": {
          "$ref": "#/$defs/TaggedValue"
        },
        "strength": {
          "$ref": "#/$defs/TaggedValue"
        }
      },
      "required": [
        "class",
        "strength",
        "linear_mass"
      ],
      "title": "LineSpec",
      "type": "object"
    },
    "LoftPoint": {
      "additionalProperties": false,
      "description": "One station of a gore loft (lobe bulge between load tapes).\n\nAttributes\n----------\nstation : float\n    Position along the load tape as a fraction of the tape length from the mouth\n    (0) to the top opening (1), dimensionless.\nratio : float\n    Lobe-radius ratio :math:`k = \\rho / r`: radius of the fabric lobe between two\n    adjacent tapes over the tape radius, dimensionless. 1 is the small-bulge gore\n    (lobe on the circle through the tapes); larger is flatter, smaller is fuller.",
      "properties": {
        "ratio": {
          "exclusiveMinimum": 0,
          "title": "Ratio",
          "type": "number"
        },
        "station": {
          "maximum": 1,
          "minimum": 0,
          "title": "Station",
          "type": "number"
        }
      },
      "required": [
        "station",
        "ratio"
      ],
      "title": "LoftPoint",
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
      "description": "One horizontal panel row of every gore.\n\nAttributes\n----------\nletter : str\n    Row letter (mouth first).\nfinished_height : float\n    Finished height along the tape, m.\nzone : str, optional\n    Material zone (key of ``zones``), e.g. ``mouth`` for a Nomex row; a pattern\n    annotation of the row overrides it; default the first zone.",
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
        },
        "zone": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Zone"
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
      "description": "The parachute (deflation port) that closes the crown opening from inside.\n\nThe parachute's diameter follows from the envelope: it covers the parachute hole\n(``gores.parachute_hole_diameter``) and overlaps the envelope by ``gores.seal_overlap``\nmeasured along the fabric. One shroud line and one centralising line leave each\nradial seam of the parachute.\n\nAttributes\n----------\npanel_count : int\n    Radial parachute panels (and shroud lines), >= 3.\nbillow : float\n    Rise of the inflated cap over the hole, as a fraction of the hole diameter\n    (0 = flat), dimensionless.\nzone : str, optional\n    Material zone of the parachute fabric; default the design's first zone.\nshroud_attachment : float\n    Distance along the envelope load tape from the parachute edge down to where each\n    shroud line is attached, m.\ncentralizing_depth : float\n    Depth of the centralising-line confluence (red-line attachment) below the crown\n    opening, m.\nshroud_line, centralizing_line : LineSpec\n    Line classes.\ncrown_ring : RingSpec, optional\n    Ring sewn into the rim of the crown opening (its diameter is the opening's).\ncentre_ring : RingSpec, optional\n    Ring at the parachute apex where the radial tapes meet and the crown line is\n    attached; the parachute panels end at it.\ncentre_ring_diameter : float, optional\n    m; required with ``centre_ring``.",
      "properties": {
        "billow": {
          "maximum": 0.5,
          "minimum": 0.0,
          "title": "Billow",
          "type": "number"
        },
        "centralizing_depth": {
          "exclusiveMinimum": 0.0,
          "title": "Centralizing Depth",
          "type": "number"
        },
        "centralizing_line": {
          "$ref": "#/$defs/LineSpec"
        },
        "centre_ring": {
          "anyOf": [
            {
              "$ref": "#/$defs/RingSpec"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "centre_ring_diameter": {
          "anyOf": [
            {
              "exclusiveMinimum": 0.0,
              "type": "number"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Centre Ring Diameter"
        },
        "crown_ring": {
          "anyOf": [
            {
              "$ref": "#/$defs/RingSpec"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "panel_count": {
          "minimum": 3,
          "title": "Panel Count",
          "type": "integer"
        },
        "shroud_attachment": {
          "exclusiveMinimum": 0.0,
          "title": "Shroud Attachment",
          "type": "number"
        },
        "shroud_line": {
          "$ref": "#/$defs/LineSpec"
        },
        "zone": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Zone"
        }
      },
      "required": [
        "panel_count",
        "billow",
        "shroud_attachment",
        "centralizing_depth",
        "shroud_line",
        "centralizing_line"
      ],
      "title": "ParachuteSpec",
      "type": "object"
    },
    "RedLineSpec": {
      "additionalProperties": false,
      "description": "The red line (deflation line) from the parachute confluence to the basket.\n\nAttributes\n----------\nname : str\n    Line name printed on the rigging sheet.\nguide_seam : int\n    Vertical load tape (seam number, 1..N) the line is led down; its guide ring sits at\n    the mouth on that tape.\nspare_length : float\n    Extra length below the basket attachment for handling and tie-off, m.\nline : LineSpec\n    Line class.",
      "properties": {
        "guide_seam": {
          "minimum": 1,
          "title": "Guide Seam",
          "type": "integer"
        },
        "line": {
          "$ref": "#/$defs/LineSpec"
        },
        "name": {
          "default": "red line",
          "title": "Name",
          "type": "string"
        },
        "spare_length": {
          "minimum": 0.0,
          "title": "Spare Length",
          "type": "number"
        }
      },
      "required": [
        "guide_seam",
        "spare_length",
        "line"
      ],
      "title": "RedLineSpec",
      "type": "object"
    },
    "RiggingSpec": {
      "additionalProperties": false,
      "description": "Rigging: crown line, red line, flying wires and the rigging load case.\n\nAttributes\n----------\ncrown_line : str\n    Crown line name.\nload_factor : TaggedValue\n    Limit flight load factor applied to rigging loads, dimensionless.\nrequired_safety_factor : TaggedValue\n    Minimum breaking-strength-to-limit-load ratio of lines, wires and load tapes,\n    dimensionless.\nred_line : RedLineSpec, optional\nflying_wires : FlyingWireSpec, optional",
      "properties": {
        "crown_line": {
          "title": "Crown Line",
          "type": "string"
        },
        "flying_wires": {
          "anyOf": [
            {
              "$ref": "#/$defs/FlyingWireSpec"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "load_factor": {
          "$ref": "#/$defs/TaggedValue"
        },
        "red_line": {
          "anyOf": [
            {
              "$ref": "#/$defs/RedLineSpec"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "required_safety_factor": {
          "$ref": "#/$defs/TaggedValue"
        }
      },
      "required": [
        "crown_line",
        "load_factor",
        "required_safety_factor"
      ],
      "title": "RiggingSpec",
      "type": "object"
    },
    "RingSpec": {
      "additionalProperties": false,
      "description": "A load ring (crown ring at the opening rim, centre ring of the parachute).\n\nAttributes\n----------\nring_class : str\n    Ring description (alias ``class``), e.g. \"aluminium rod ring 8 mm\".\nlinear_mass : TaggedValue\n    Mass per length of the ring, kg/m.\nstrength : TaggedValue\n    Allowable axial (hoop) force of the ring section, N.\nrequired_safety_factor : TaggedValue\n    Minimum strength-to-limit-load ratio, dimensionless.",
      "properties": {
        "class": {
          "title": "Class",
          "type": "string"
        },
        "linear_mass": {
          "$ref": "#/$defs/TaggedValue"
        },
        "required_safety_factor": {
          "$ref": "#/$defs/TaggedValue"
        },
        "strength": {
          "$ref": "#/$defs/TaggedValue"
        }
      },
      "required": [
        "class",
        "linear_mass",
        "strength",
        "required_safety_factor"
      ],
      "title": "RingSpec",
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
    "ScoopSpec": {
      "additionalProperties": false,
      "description": "A scoop: fabric hanging below the mouth over consecutive gores.\n\nAttributes\n----------\nfirst_gore : int\n    First gore (1..N) the scoop hangs from.\ngore_count : int\n    Consecutive gores it spans (N: a full skirt).\nheight : float\n    Vertical depth below the mouth, m.\nflare_deg : float\n    Outward angle of the scoop from the vertical, degrees (boundary format).\nzone : str, optional\n    Material zone; default the mouth row's zone.",
      "properties": {
        "first_gore": {
          "minimum": 1,
          "title": "First Gore",
          "type": "integer"
        },
        "flare_deg": {
          "default": 10.0,
          "exclusiveMaximum": 60.0,
          "minimum": 0.0,
          "title": "Flare Deg",
          "type": "number"
        },
        "gore_count": {
          "minimum": 1,
          "title": "Gore Count",
          "type": "integer"
        },
        "height": {
          "exclusiveMinimum": 0.0,
          "title": "Height",
          "type": "number"
        },
        "zone": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Zone"
        }
      },
      "required": [
        "first_gore",
        "gore_count",
        "height"
      ],
      "title": "ScoopSpec",
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
    "TaggedValue": {
      "additionalProperties": false,
      "description": "A value with its provenance.\n\nAttributes\n----------\nvalue : float\n    Value in the SI unit stated by the field that holds it.\nsource : {\"datasheet\", \"measured\", \"assumed\"}\n    Provenance tag.\nnote : str\n    Reference or remark (datasheet name, regulation, \"generic value\").",
      "properties": {
        "note": {
          "default": "",
          "title": "Note",
          "type": "string"
        },
        "source": {
          "enum": [
            "datasheet",
            "measured",
            "assumed"
          ],
          "title": "Source",
          "type": "string"
        },
        "value": {
          "title": "Value",
          "type": "number"
        }
      },
      "required": [
        "value",
        "source"
      ],
      "title": "TaggedValue",
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
    },
    "TurningVentSpec": {
      "additionalProperties": false,
      "description": "A turning (rotation) vent: a vertical seam left open over some rows.\n\nAttributes\n----------\nname : str\n    Vent name.\nseam : int\n    Vertical seam number (1..N); seam k joins gore k and gore k+1.\nrows : list of str\n    Consecutive panel rows over which the seam is open.\ndirection : {\"clockwise\", \"counterclockwise\"}\n    Rotation the vent's jet gives the balloon, seen from above.\nopening_width : float\n    Gap width when the vent is pulled fully open, m.\ndischarge_coefficient : TaggedValue\n    Orifice discharge coefficient, dimensionless.\ncontrol_line : LineSpec\n    Line from the vent to the basket.\nsimulate_open : bool\n    Leave the seam open in the structural model (vent open); default closed.",
      "properties": {
        "control_line": {
          "$ref": "#/$defs/LineSpec"
        },
        "direction": {
          "enum": [
            "clockwise",
            "counterclockwise"
          ],
          "title": "Direction",
          "type": "string"
        },
        "discharge_coefficient": {
          "$ref": "#/$defs/TaggedValue"
        },
        "name": {
          "title": "Name",
          "type": "string"
        },
        "opening_width": {
          "exclusiveMinimum": 0.0,
          "title": "Opening Width",
          "type": "number"
        },
        "rows": {
          "items": {
            "type": "string"
          },
          "minItems": 1,
          "title": "Rows",
          "type": "array"
        },
        "seam": {
          "minimum": 1,
          "title": "Seam",
          "type": "integer"
        },
        "simulate_open": {
          "default": false,
          "title": "Simulate Open",
          "type": "boolean"
        }
      },
      "required": [
        "name",
        "seam",
        "rows",
        "direction",
        "opening_width",
        "discharge_coefficient",
        "control_line"
      ],
      "title": "TurningVentSpec",
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
      "default": 3,
      "title": "Schema Version",
      "type": "integer"
    },
    "scoop": {
      "anyOf": [
        {
          "$ref": "#/$defs/ScoopSpec"
        },
        {
          "type": "null"
        }
      ],
      "default": null
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
    "turning_vents": {
      "items": {
        "$ref": "#/$defs/TurningVentSpec"
      },
      "title": "Turning Vents",
      "type": "array"
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
