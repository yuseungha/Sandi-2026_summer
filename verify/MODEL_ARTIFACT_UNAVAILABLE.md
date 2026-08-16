# C-B6 TFLite artifact status

`full_integer_int8.tflite` and `float_reference.tflite` are deliberately absent. The locked expected SHA-256 values are retained in `verify/contracts/c_b6_tflite_contract.json`, but no candidate binary was available in either supplied source repository.

Do not copy or adapt the team `co2_occupancy_int8_v0.1.0.tflite`: its `CO2Interpreter.predict(co2_slope, humidity, co2_ppm)` contract has three inputs and is incompatible with C-B6 `['CO2', 'CO2_slope']`.
