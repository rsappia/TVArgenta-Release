// encoder_reader.c — libgpiod v2.x

/* SPDX-License-Identifier: LicenseRef-TVArgenta-NC-Attribution-Consult-First
 * Project: TVArgenta — Retro TV
 * Author: Ricardo Sappia (rsflightronics@gmail.com)
 * © 2025 Ricardo Sappia. All rights reserved.
 * License: Non-Commercial, Attribution, Prior Consultation. Provided AS IS, no warranty.
 * See LICENSE for full terms.
 */

#include <gpiod.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <unistd.h>

#define CHIP_NAME "/dev/gpiochip0"
#define CLK 23
#define DT  17
#define SW  27

int main(void) {
    struct gpiod_chip *chip = gpiod_chip_open(CHIP_NAME);
    if (!chip) { perror("gpiod_chip_open"); return 1; }

    // Settings: CLK/DT input; SW input con pull-up
    struct gpiod_line_settings *enc_in = gpiod_line_settings_new();
    gpiod_line_settings_set_direction(enc_in, GPIOD_LINE_DIRECTION_INPUT);

    struct gpiod_line_settings *btn_in = gpiod_line_settings_new();
    gpiod_line_settings_set_direction(btn_in, GPIOD_LINE_DIRECTION_INPUT);
    gpiod_line_settings_set_bias(btn_in, GPIOD_LINE_BIAS_PULL_UP);

    struct gpiod_request_config *req_cfg = gpiod_request_config_new();
    gpiod_request_config_set_consumer(req_cfg, "encoder");

    struct gpiod_line_config *line_cfg = gpiod_line_config_new();

    unsigned int off_cd[2] = { CLK, DT };
    if (gpiod_line_config_add_line_settings(line_cfg, off_cd, 2, enc_in) < 0) {
        perror("line_config_add_line_settings(CLK,DT)"); return 1;
    }
    unsigned int off_sw[1] = { SW };
    if (gpiod_line_config_add_line_settings(line_cfg, off_sw, 1, btn_in) < 0) {
        perror("line_config_add_line_settings(SW)"); return 1;
    }

    struct gpiod_line_request *req = gpiod_chip_request_lines(chip, req_cfg, line_cfg);
    if (!req) { perror("gpiod_chip_request_lines"); return 1; }

    int clk_prev = gpiod_line_request_get_value(req, CLK);
    int dt_prev  = gpiod_line_request_get_value(req, DT);
    int sw_prev  = gpiod_line_request_get_value(req, SW);
    if (clk_prev < 0 || dt_prev < 0 || sw_prev < 0) { perror("get init"); return 1; }

    int sw_pressed = 0, sw_released = 0;

    while (1) {
        int clk = gpiod_line_request_get_value(req, CLK);
        int dt  = gpiod_line_request_get_value(req, DT);
        int sw  = gpiod_line_request_get_value(req, SW);
        if (clk < 0 || dt < 0 || sw < 0) { perror("get"); break; }

        // ROTARY: flanco descendente en CLK
        if (clk != clk_prev) {
            if (clk == 0) {
                if (dt != clk) printf("ROTARY_CW\n");
                else           printf("ROTARY_CCW\n");
                fflush(stdout);
            }
            clk_prev = clk;
        }

        // BOTÓN (pull-up: 1 libre, 0 presionado)
        if (sw != sw_prev) {
            if (sw == 0 && !sw_pressed) {
                printf("BTN_PRESS\n"); fflush(stdout);
                sw_pressed = 1; sw_released = 0;
            } else if (sw == 1 && !sw_released && sw_pressed) {
                printf("BTN_RELEASE\n"); fflush(stdout);
                sw_pressed = 0; sw_released = 1;
            }
            sw_prev = sw;
        }

        usleep(3000);
    }

    gpiod_line_request_release(req);
    gpiod_line_config_free(line_cfg);
    gpiod_request_config_free(req_cfg);
    gpiod_line_settings_free(enc_in);
    gpiod_line_settings_free(btn_in);
    gpiod_chip_close(chip);
    return 0;
}
