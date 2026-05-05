/**
 * @fileoverview Form and input components entry point.
 *
 * Every interactive control used to collect or edit data.
 */

import { BuiltinColorPicker } from "./form/color-picker.js";
import { BuiltinCommandPalette } from "./form/command-palette.js";
import { BuiltinContactForm } from "./form/contact-form.js";
import { BuiltinDatePicker } from "./form/date-picker.js";
import { BuiltinDragTiles } from "./form/drag-tiles.js";
import { BuiltinDragUploadZone } from "./form/drag-upload-zone.js";
import { BuiltinFileUploader } from "./form/file-uploader.js";
import { BuiltinFilterBar } from "./form/filter-bar.js";
import { BuiltinInputCreditCard } from "./form/input-credit-card.js";
import { BuiltinInputOtp } from "./form/input-otp.js";
import { BuiltinInputTags } from "./form/input-tags.js";
import { BuiltinSchemaForm } from "./form/schema-form.js";
import { BuiltinSliderRange } from "./form/slider-range.js";
import { BuiltinTimePicker } from "./form/time-picker.js";

export {
  BuiltinColorPicker, BuiltinCommandPalette, BuiltinContactForm, BuiltinDatePicker, BuiltinDragTiles, BuiltinDragUploadZone, BuiltinFileUploader, BuiltinFilterBar, BuiltinInputCreditCard, BuiltinInputOtp, BuiltinInputTags, BuiltinSchemaForm, BuiltinSliderRange, BuiltinTimePicker
};

const _REGISTRY = [
  ["builtin-color-picker", BuiltinColorPicker],
  ["builtin-command-palette", BuiltinCommandPalette],
  ["builtin-contact-form", BuiltinContactForm],
  ["builtin-date-picker", BuiltinDatePicker],
  ["builtin-drag-tiles", BuiltinDragTiles],
  ["builtin-drag-upload-zone", BuiltinDragUploadZone],
  ["builtin-file-uploader", BuiltinFileUploader],
  ["builtin-filter-bar", BuiltinFilterBar],
  ["builtin-input-credit-card", BuiltinInputCreditCard],
  ["builtin-input-otp", BuiltinInputOtp],
  ["builtin-input-tags", BuiltinInputTags],
  ["builtin-schema-form", BuiltinSchemaForm],
  ["builtin-slider-range", BuiltinSliderRange],
  ["builtin-time-picker", BuiltinTimePicker],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
