from distance_utils import haversine_miles

# Mock beneficiary coordinates (New York City)
beneficiary_lat = 40.7128
beneficiary_lon = -74.0060

# Mock organization coordinates (Los Angeles)
organization_lat = 34.0522
organization_lon = -118.2437

distance = haversine_miles(
    beneficiary_lat,
    beneficiary_lon,
    organization_lat,
    organization_lon
)

print(f"Distance: {distance} miles")

assert 2440 < distance < 2450
print("Test passed!")