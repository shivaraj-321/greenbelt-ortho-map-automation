import arcpy, os

# ===============================================================================================================
# Property we want to work and location where the final pdf go
# ===============================================================================================================

property_key = arcpy.GetParameterAsText(0)
output_folder = arcpy.GetParameterAsText(1)
'''
property_key = "TOP02"
output_folder = r"D:\Greenbelt\Greenbelt_Ortho_Automation\output"
'''
# ===============================================================================================================
# Project, Map, Layout, Map Frame AND Layers
# ===============================================================================================================

aprx = arcpy.mp.ArcGISProject("CURRENT")
m = aprx.listMaps("Ortho Map")[0]
layout = aprx.listLayouts("Ortho_Portrait")[0]
map_frame = layout.listElements("MAPFRAME_ELEMENT", "Map Frame")[0]
property_layer = m.listLayers("Greenbelt Property")[0]
other_protected = m.listLayers("Other Protected")[0]

# ===============================================================================================================
# SELECT PROPERTY
# ===============================================================================================================

#clear any existing selection
arcpy.management.SelectLayerByAttribute(property_layer, "CLEAR_SELECTION")
where_clause = f"Key_ = '{property_key}'"
arcpy.management.SelectLayerByAttribute(property_layer, "NEW_SELECTION", where_clause)

# ===============================================================================================================
# GET PROPERTY INFORMATION
# ===============================================================================================================

property_name = None
property_town = None

with arcpy.da.SearchCursor(property_layer, ["Property", "Town"], where_clause) as cursor:
    for name, town in cursor:
        property_name = name
        property_town = town
        break
# Validate Property
if property_name is None:
    raise ValueError(f"Property not found: {property_key}")

# ===============================================================================================================
# ZOOM TO PROPERTY
# ===============================================================================================================

parcel_extent = map_frame.getLayerExtent(property_layer, True, True)   # Get the selected property's extent
map_frame.camera.setExtent(parcel_extent)                              # Zoom the map frame to the property
map_frame.camera.scale *= 1.10                                         # Zoom out by 10%

print("=" * 50)
print(f"Property: {property_key}")
print(f"Property name: {property_name}")
print(f"Map scale: 1:{map_frame.camera.scale:,.0f}")
print("=" * 50)


# ===============================================================================================================
# CREATE RED BOUNDARY FOR SELECTED PROPERTY
# ===============================================================================================================

# 1. Remove previous highlighted layer
for lyr in m.listLayers("color_boundary_parcel"):
    m.removeLayer(lyr)

# 2. Set temporary output location
arcpy.env.overwriteOutput = True
arcpy.env.addOutputsToMap = False

output_fc = os.path.join(
    arcpy.env.scratchGDB,
    "color_boundary_parcel"
)
# Delete previous feature class if it exists
if arcpy.Exists(output_fc):
    arcpy.management.Delete(output_fc)

# 3. Export selected parcel
arcpy.management.CopyFeatures(
    property_layer,
    output_fc
)

# 4. Add exported parcel to map
red_layer = m.addDataFromPath(output_fc)
red_layer.name = "color_boundary_parcel"

# 5. Change symbology
sym = red_layer.symbology
sym.updateRenderer("SimpleRenderer")

symbol = sym.renderer.symbol

# Transparent fill
symbol.color = {"RGB": [255, 255, 255, 0]}

# Red boundary
symbol.outlineColor = {"RGB": [255, 0, 0, 100]}
symbol.outlineWidth = 2.5

sym.renderer.symbol = symbol
red_layer.symbology = sym

# 6. Move red boundary layer above original parcels
m.moveLayer(property_layer, red_layer, "BEFORE")

# 7. Clear selection
arcpy.management.SelectLayerByAttribute(
    property_layer, "CLEAR_SELECTION"
)


# ===============================================================================================================
# UPDATE MAP TITLE
# ===============================================================================================================

title_element = layout.listElements("TEXT_ELEMENT", "Title")[0]      # find the title element in the layout

title_element.text = (f"{property_key} {property_name} - {property_town}")   # replace/updatee the map title

'''
# ===============================================================================================================
# PROPERTY LABEL
# ===============================================================================================================

property_text = layout.listElements("TEXT_ELEMENT", "Text 9")[0]

property_text.text = property_name

# Get the selected property's geometry
with arcpy.da.SearchCursor(property_layer, ["SHAPE@"], where_clause) as cursor:

    geometry = next(cursor)[0]


center = geometry.labelPoint

extent = map_frame.camera.getExtent()

relative_x = ((center.X - extent.XMin) / (extent.XMax - extent.XMin))

relative_y = ((center.Y - extent.YMin) / (extent.YMax - extent.YMin))

label_x = (map_frame.elementPositionX + relative_x * map_frame.elementWidth)

label_y = (map_frame.elementPositionY + relative_y * map_frame.elementHeight)

property_text.setAnchor("CENTER_POINT")

property_text.elementPositionX = label_x
property_text.elementPositionY = label_y
'''

# ===============================================================================================================
# OTHER PROTECTED DEFINITION QUERY
# ===============================================================================================================

other_protected.definitionQuery = ""

property_geometries = []

with arcpy.da.SearchCursor( property_layer, ["SHAPE@"], where_clause) as cursor:
    for row in cursor:
        if row[0] is not None:
            property_geometries.append(row[0])

if not property_geometries:
    raise ValueError(
        f"No geometry found for {property_key}"
    )


property_geometry = property_geometries[0]

for geom in property_geometries[1:]:
    property_geometry = property_geometry.union(geom)


oid_field = arcpy.Describe(other_protected).OIDFieldName

matching_oids = []


with arcpy.da.SearchCursor(other_protected, [oid_field, "SHAPE@", "LEV_PROT"]) as cursor:
    for oid, other_geometry, protection in cursor:
        if protection != "P":
            continue

        if other_geometry is None:
            continue

        inside_point = other_geometry.labelPoint

        if not inside_point.disjoint(property_geometry):
            matching_oids.append(oid)

matching_oids = sorted(set(matching_oids))


if matching_oids:

    oid_list = ", ".join(
        str(oid) for oid in matching_oids
    )

    final_query = (
        "LEV_PROT = 'P' "
        f"AND {oid_field} NOT IN ({oid_list})"
    )

else:

    final_query = "LEV_PROT = 'P'"

other_protected.definitionQuery = final_query

# ===============================================================================================================
# AUTOMATIC SCALE BAR SELECTION
# ===============================================================================================================

# Final location of the scale bar
SCALEBAR_X = 5.3485
SCALEBAR_Y = 1.185

# Maximum allowed width so scale bar does not
# touch the North Arrow / layout frame
MAX_WIDTH = 2.30


# ===============================================================================================================
# Get all scale bars
# ===============================================================================================================

scale_bars = []

for i in range(1, 16):

    name = f"ScaleBar{i}"

    elements = layout.listElements(
        "MAPSURROUND_ELEMENT",
        name
    )

    if elements:
        scale_bars.append(elements[0])


# Add ScaleBarSmall
small = layout.listElements("MAPSURROUND_ELEMENT", "ScaleBarSmall")[0]

scale_bars.append(small)


# ===============================================================================================================
# Move ALL scale bars off the page first
# ===============================================================================================================

for sb in scale_bars:

    sb.elementPositionX = -6
    sb.elementPositionY = -7


# ===============================================================================================================
# Find scale bars that fit
# ===============================================================================================================

valid_bars = []

for sb in scale_bars:

    width = sb.elementWidth
    cim = sb.getDefinition("V3")

    division = cim.division
    divisions = cim.divisions
    total_distance = division * divisions

    # Total scale-bar distance must be a multiple of 50
    # and must fit safely before the North Arrow
    if total_distance % 50 == 0 and width <= MAX_WIDTH:
        valid_bars.append(sb)


# ===============================================================================================================
# Select largest scale bar that safely fits
# ===============================================================================================================

if valid_bars:

    selected_bar = max(
        valid_bars,
        key=lambda sb:
            sb.getDefinition("V3").division *
            sb.getDefinition("V3").divisions
    )

else:
    selected_bar = small


# ===============================================================================================================
# Move selected scale bar into final position
# ===============================================================================================================

selected_bar.elementPositionX = SCALEBAR_X
selected_bar.elementPositionY = SCALEBAR_Y


# ===============================================================================================================
# Print result
# ===============================================================================================================

selected_cim = selected_bar.getDefinition("V3")

print("=" * 50)
print(f"Property: {property_key}")
print(f"Map scale: 1:{map_frame.camera.scale:,.0f}")
print(f"Scale bar used: {selected_bar.name}")
print(f"Division: {selected_cim.division:,.0f} ft")
print(
    f"Total distance: "
    f"{selected_cim.division * selected_cim.divisions:,.0f} ft"
)
print(f"Scale bar width: {selected_bar.elementWidth:.4f}")
print("=" * 50)

# ===============================================================================================================
# CLEAR PROPERTY SELECTION
# ===============================================================================================================

arcpy.management.SelectLayerByAttribute(property_layer, "CLEAR_SELECTION")


# ===============================================================================================================
# EXPORT PDF
# ===============================================================================================================

os.makedirs(output_folder, exist_ok=True)


safe_property_name = (
    property_name
    .replace(" ", "_")
    .replace("/", "-")
    if property_name
    else "Unknown_Property"
)

safe_town = (
    town.replace(" ", "_")
    if town
    else "Unknown_Town"
)

pdf_name = (
    f"{property_key}_"
    f"{safe_property_name}_"
    f"{safe_town}_"
    f"Ortho_2026.pdf"
)


pdf_path = os.path.join(
    output_folder,
    pdf_name
)


layout.exportToPDF(
    pdf_path,
    resolution=300
)
print("map exported")





