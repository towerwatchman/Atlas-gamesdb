# Python3 code to demonstrate working of
# Remove K valued key from Nested Dictionary
# Using loop + isinstance() + filter()

# initializing dictionary
test_dict = {
    "gfg": {"best": 4, "good": 5},
    "is": {"better": 6, "educational": 4},
    "CS": {"priceless": 6},
}

# printing original dictionary
print("The original dictionary : " + str(test_dict))

# initializing rem_val
rem_val = "priceless"


# Remove K valued key from Nested Dictionary
# Using loop + isinstance() + filter()
def rem_vals(ele):
    global rem_val
    key, val = ele
    return val != rem_val


res = dict()
for key, val in test_dict.items():
    if isinstance(val, dict):
        res[key] = dict(filter(rem_vals, val.items()))
    else:
        res[key] = val

# printing result
print("Dictionary after removal : " + str(res))
