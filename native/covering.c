/* Same ordered dual projections as procedural_lashes.covering_shift.
 * No Blender API, allocation, threads or external runtime dependencies.
 * Build with strict floating point; never enable fast-math or FMA contraction.
 */
#include <math.h>
#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif
EXPORT int ek_covering_abi(void) { return 1; }
EXPORT int ek_covering_project(int count, int size, const double *rows,
    const double *bounds, const double *directions, const double *norm,
    double *controls, double *dual, double tolerance, int iterations)
{
    if (count < 1 || size < 1 || size > 1024 || iterations < 1) return -1;
    for (int step = 0; step < iterations; ++step) {
        for (int k = 0; k < count; ++k) {
            const double *row = rows + k * size;
            const double *direction = directions + k * size;
            double dot = 0.;
            for (int j = 0; j < size; ++j) dot += row[j] * controls[j];
            double divisor = norm[k] > 1e-20 ? norm[k] : 1e-20;
            double proposed = dual[k] + (dot - bounds[k]) / divisor;
            double amount = (proposed > 0. ? proposed : 0.) - dual[k];
            for (int j = 0; j < size; ++j) controls[j] -= amount * direction[j];
            dual[k] += amount;
        }
        double maximum = -INFINITY;
        for (int k = 0; k < count; ++k) {
            double dot = 0.;
            for (int j = 0; j < size; ++j) dot += rows[k * size + j] * controls[j];
            if (!isfinite(dot)) return -2;
            double violation = dot - bounds[k];
            if (violation > maximum) maximum = violation;
        }
        if (maximum <= tolerance) return step + 1;
    }
    return 0;
}
