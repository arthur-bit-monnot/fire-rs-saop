#include "../ext/dubins.h"
#include "../dubins3d.h"
#include <iostream>
#include "../core/structures/waypoint.h"
#include <boost/test/included/unit_test.hpp>
using namespace boost::unit_test;
using namespace std;

static double r_min = 25; // m
static double gamma_max = 0.1; // rad

bool test_length_high_alt() {
    cout << "::test_length_high_alt::" << endl;

    Waypoint3d orig {100, 100, 0, M_PI_2};
    Waypoint3d dest {0, 0, 200, 3 * M_PI_2};

    Dubins3dPathLength path(orig, dest, r_min, gamma_max);

    cout << orig << " -> " << dest << " => " << path.L << "xyz / " << path.L_2d << "xy" << endl;
    return true;
}

bool test_length_medium_alt() {
    cout << "::test_length_medium_alt::" << endl;

    Waypoint3d orig {100, 100, 0, M_PI_2};
    Waypoint3d dest {0, 0, 50, 3 * M_PI_2};

    Dubins3dPathLength path(orig, dest, r_min, gamma_max);

    cout << orig << " -> " << dest << " => " << path.L << "xyz / " << path.L_2d << "xy" << endl;
    return true;
}

bool test_medium_alt_SSLS() {
    cout << "::test_medium_alt_SSLS::" << endl;
    Waypoint3d orig {100, 100, 0, M_PI_2};
    Waypoint3d dest {0, 0, 25, 3 * M_PI_2};

    Dubins3dPathLength path(orig, dest, r_min, gamma_max);

    BOOST_TEST(path.R>=0);

    cout << orig << " -> " << dest << " => " << path.L << "xyz / " << path.L_2d << "xy" << endl;
    return true;
}

bool test_length_low_alt() {
    cout << "::test_length_low_alt::" << endl;

    Waypoint3d orig {100, 100, 0, M_PI_2};
    Waypoint3d dest {0, 0, 15, 3 * M_PI_2};

    Dubins3dPathLength path(orig, dest, r_min, gamma_max);

    cout << orig << " -> " << dest << " => " << path.L << "xyz / " << path.L_2d << "xy" << endl;
    return true;
}

bool test_triangleineq_flat() {
    Waypoint3d a {0, 0, 0, 0};
    Waypoint3d b {100, 100, 0, M_PI_2};
    Waypoint3d c {0, 100, 0, M_PI};
    Dubins3dPathLength path_ab(a, b, r_min, gamma_max);
    Dubins3dPathLength path_bc(b, c, r_min, gamma_max);
    Dubins3dPathLength path_ac(a, c, r_min, gamma_max);

    if (path_ab.configuration_2d && path_bc.configuration_2d && path_ac.configuration_2d) {
        BOOST_TEST(path_ab.L + path_bc.L > path_ac.L);
        BOOST_TEST(path_ab.L_2d + path_bc.L_2d > path_ac.L_2d);
        return true;
    }

    return false;
}

bool test_triangleineq_highest() {
    Waypoint3d a {0, 0, 0, 0};
    Waypoint3d b {100, 100, 500, M_PI_2};
    Waypoint3d c {200, 100, 1000, M_PI};
    Dubins3dPathLength path_ab(a, b, r_min, gamma_max);
    Dubins3dPathLength path_bc(b, c, r_min, gamma_max);
    Dubins3dPathLength path_ac(a, c, r_min, gamma_max);

    if (path_ab.configuration_2d && path_bc.configuration_2d && path_ac.configuration_2d) {
        BOOST_TEST(path_ab.L + path_bc.L > path_ac.L);
        BOOST_TEST(path_ab.L_2d + path_bc.L_2d > path_ac.L_2d);
        return true;
    }

    return false;
}


bool test_triangleineq_high() {
    Waypoint3d a {0, 0, 0, 0};
    Waypoint3d b {100, 100, 50, M_PI_2};
    Waypoint3d c {200, 100, 100, M_PI};
    Dubins3dPathLength path_ab(a, b, r_min, gamma_max);
    Dubins3dPathLength path_bc(b, c, r_min, gamma_max);
    Dubins3dPathLength path_ac(a, c, r_min, gamma_max);

    if (path_ab.configuration_2d && path_bc.configuration_2d && path_ac.configuration_2d) {
        BOOST_TEST(path_ab.L + path_bc.L > path_ac.L);
        BOOST_TEST(path_ab.L_2d + path_bc.L_2d > path_ac.L_2d);
        return true;
    }

    return false;
}

bool test_length_flat() {
    DubinsPath path2d;
    Waypoint3d orig {100, 100, 0, M_PI_2};
    Waypoint3d dest {0, 0, 0, 3 * M_PI_2};

    double orig_array[3] {orig.x, orig.y, orig.dir};
    double dest_array[3] {dest.x, dest.y, dest.dir};

    Dubins3dPathLength path3d(orig, dest, r_min, gamma_max);
    dubins_init(orig_array, dest_array, r_min, &path2d);

    cout << orig << " -> " << dest << " => " << path3d.L << "xyz / " << path3d.L_2d << "xy" << endl;
    cout << dubins_path_length(&path2d) << " type=" << dubins_path_type(&path2d) << endl;

    BOOST_TEST(path3d.L == dubins_path_length(&path2d));
    return path3d.L == dubins_path_length(&path2d);
}

test_suite* dubins_test_suite() {
    test_suite* ts1 = BOOST_TEST_SUITE("dubins_tests");
    ts1->add(BOOST_TEST_CASE(&test_length_flat));
    ts1->add(BOOST_TEST_CASE(&test_length_low_alt));
    ts1->add(BOOST_TEST_CASE(&test_medium_alt_SSLS));
    ts1->add(BOOST_TEST_CASE(&test_length_medium_alt));
    ts1->add(BOOST_TEST_CASE(&test_length_high_alt));
    ts1->add(BOOST_TEST_CASE(&test_length_flat));
    ts1->add(BOOST_TEST_CASE(&test_triangleineq_flat));
    ts1->add(BOOST_TEST_CASE(&test_triangleineq_highest));
    ts1->add(BOOST_TEST_CASE(&test_triangleineq_high));
    return ts1;
}
