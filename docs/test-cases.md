# Test cases — Mixlumo

Generated from `pytest --collect-only` on 2026-11-24. Results: the full quality gate (`run_tests.ps1 -Gpu`) of 2026-11-24 (release build of 1.2.0) passed every case below, nothing skipped. The packaged app is also tested by `scripts/smoke_test_exe.py` and `scripts/test-installer.ps1`. UI tests run once per browser (Chromium and Microsoft Edge).

**347 test cases** in 11 files.

## End-to-end — main journey on GPU (1)

`tests/e2e/test_split_gpu.py` · Stage 8 of `run_tests.ps1`

| Group | Test case |
|---|---|
| — | `test_split_with_live_progress_and_mixer` |

## End-to-end — browser UI (Chromium + Edge) (33)

`tests/e2e/test_ui.py` · Stage 5 of `run_tests.ps1`

| Group | Test case |
|---|---|
| — | `test_loads_and_navigates` |
| — | `test_run_button_disabled_until_upload` |
| — | `test_feedback_submit_and_list` |
| — | `test_feedback_validation_messages` |
| — | `test_feedback_xss_is_rendered_as_text` |
| — | `test_roadmap_voting` |
| — | `test_faq_opens` |
| — | `test_honeypot_is_invisible_to_people` |
| — | `test_cut_flow` |
| — | `test_spoofed_upload_shows_error` |
| — | `test_remove_file_resets_dropzone` |
| — | `test_replace_file` |
| — | `test_job_failure_state` |
| — | `test_analyze_flow` |
| — | `test_pitch_flow` |
| — | `test_speed_presets_and_keep_pitch` |
| — | `test_source_player_plays_uploaded_song` |
| — | `test_live_pitch_and_speed_preview` |
| — | `test_effect_controls_disabled_until_switched_on` |
| — | `test_effect_presets` |
| — | `test_live_lofi_and_echo_preview` |
| — | `test_render_with_lofi_and_echo` |
| — | `test_removing_file_stops_preview` |
| — | `test_join_reorder_and_join` |
| — | `test_convert_to_ogg` |
| — | `test_split_options_and_estimate` |
| — | `test_responsive_no_horizontal_scroll[chromium-375-812]` |
| — | `test_responsive_no_horizontal_scroll[chromium-768-1024]` |
| — | `test_responsive_no_horizontal_scroll[chromium-1440-900]` |
| — | `test_every_control_has_an_accessible_name` |
| — | `test_keyboard_opens_file_picker` |
| — | `test_removing_file_deletes_upload` |
| — | `test_images_and_lang` |

## End-to-end — themes, accents, accessibility (Chromium + Edge) (24)

`tests/e2e/test_theme.py` · Stage 5 of `run_tests.ps1`

| Group | Test case |
|---|---|
| — | `test_switch_theme_and_remember_it` |
| — | `test_auto_follows_windows_setting[chromium-light-True]` |
| — | `test_auto_follows_windows_setting[chromium-dark-False]` |
| — | `test_accent_presets_and_custom_colour` |
| — | `test_light_accent_gets_dark_button_text` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Violet-light]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Violet-dark]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Blue-light]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Blue-dark]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Teal-light]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Teal-dark]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Green-light]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Green-dark]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Orange-light]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Orange-dark]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Pink-light]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Pink-dark]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Red-light]` |
| — | `test_text_contrast_meets_wcag_aa[chromium-Red-dark]` |
| — | `test_every_page_renders_in_light_theme` |
| — | `test_no_sideways_scroll_with_wcag_text_spacing[chromium-320]` |
| — | `test_no_sideways_scroll_with_wcag_text_spacing[chromium-375]` |
| — | `test_brand_and_search_tags` |
| — | `test_copyright_notice_is_visible` |

## Integration, security & load — HTTP API (64)

`tests/test_api.py` · Stage 4 of `run_tests.ps1`

| Group | Test case |
|---|---|
| — | `test_index_page` |
| — | `test_info` |
| — | `test_info_leaks_no_secrets` |
| — | `test_importing_server_never_deletes_files` |
| — | `test_clean_temp_files_only_on_explicit_call` |
| — | `test_second_instance_detects_port_in_use` |
| — | `test_server_only_listens_on_localhost` |
| TestUpload | `test_valid_audio` |
| TestUpload | `test_video_is_accepted` |
| TestUpload | `test_mime_spoofing_is_rejected[spoofed_mp3]` |
| TestUpload | `test_mime_spoofing_is_rejected[png_as_wav]` |
| TestUpload | `test_empty_file` |
| TestUpload | `test_size_limit` |
| TestUpload | `test_path_traversal_filename_is_neutralised[../../evil.wav]` |
| TestUpload | `test_path_traversal_filename_is_neutralised[..\\..\\evil.wav]` |
| TestUpload | `test_path_traversal_filename_is_neutralised[C:\\Windows\\evil.wav]` |
| TestUpload | `test_path_traversal_filename_is_neutralised[/etc/evil.wav]` |
| TestUpload | `test_zero_length_audio_is_rejected` |
| TestUpload | `test_missing_file_field` |
| TestUpload | `test_delete_upload` |
| TestJobs | `test_unknown_tool` |
| TestJobs | `test_missing_upload` |
| TestJobs | `test_unknown_upload_id` |
| TestJobs | `test_params_must_be_object` |
| TestJobs | `test_raw_file_paths_cannot_be_injected` |
| TestJobs | `test_join_requires_list` |
| TestJobs | `test_unknown_job` |
| TestJobs | `test_full_lifecycle_cut` |
| TestJobs | `test_every_file_tool[analyze-params0]` |
| TestJobs | `test_every_file_tool[pitch-params1]` |
| TestJobs | `test_every_file_tool[pitch-params2]` |
| TestJobs | `test_every_file_tool[convert-params3]` |
| TestJobs | `test_every_file_tool[cut-params4]` |
| TestJobs | `test_every_format_in_worker_thread[wav]` |
| TestJobs | `test_every_format_in_worker_thread[mp3]` |
| TestJobs | `test_every_format_in_worker_thread[flac]` |
| TestJobs | `test_every_format_in_worker_thread[ogg]` |
| TestJobs | `test_every_format_in_worker_thread[m4a]` |
| TestJobs | `test_join` |
| TestJobs | `test_validation_error_is_reported_on_job` |
| TestJobs | `test_unexpected_exception_is_reported` |
| TestJobs | `test_mix_rejects_foreign_paths` |
| TestJobs | `test_mix_from_real_stems` |
| TestJobs | `test_jobs_run_one_at_a_time_in_order` |
| TestJobs | `test_progress_is_monotonic_and_has_eta` |
| TestJobs | `test_instant_progress_updates_do_not_crash` |
| TestJobs | `test_pitch_with_no_change_completes` |
| TestJobs | `test_progress_never_goes_backwards` |
| TestJobs | `test_finished_jobs_are_pruned` |
| TestFiles | `test_static_path_traversal[/files/../server.py]` |
| TestFiles | `test_static_path_traversal[/files/..%2F..%2Fserver.py]` |
| TestFiles | `test_static_path_traversal[/files/%2e%2e/%2e%2e/server.py]` |
| TestFiles | `test_static_path_traversal[/static/../server.py]` |
| TestFiles | `test_open_folder_outside_output_is_refused` |
| TestFiles | `test_open_output_folder` |
| TestGpuRelease | `test_release_endpoint` |
| TestGpuRelease | `test_idle_app_releases_gpu` |
| TestGpuRelease | `test_recent_activity_keeps_model_warm` |
| TestGpuRelease | `test_never_unloads_during_a_job` |
| TestGpuRelease | `test_nothing_to_release` |
| TestGpuRelease | `test_finishing_a_job_counts_as_activity` |
| TestGpuRelease | `test_separation_goes_through_worker` |
| TestGpuRelease | `test_worker_crash_is_reported_not_fatal` |
| — | `test_concurrent_requests` |

## Integration — Help & Feedback (65)

`tests/test_feedback.py` · Stage 4 of `run_tests.ps1`

| Group | Test case |
|---|---|
| TestValidate | `test_minimal_valid` |
| TestValidate | `test_every_category[feature]` |
| TestValidate | `test_every_category[suggestion]` |
| TestValidate | `test_every_category[bug]` |
| TestValidate | `test_every_category[question]` |
| TestValidate | `test_rejects[bad0]` |
| TestValidate | `test_rejects[bad1]` |
| TestValidate | `test_rejects[bad2]` |
| TestValidate | `test_rejects[bad3]` |
| TestValidate | `test_rejects[bad4]` |
| TestValidate | `test_rejects[bad5]` |
| TestValidate | `test_rejects[bad6]` |
| TestValidate | `test_rejects[bad7]` |
| TestValidate | `test_rejects[bad8]` |
| TestValidate | `test_rejects[bad9]` |
| TestValidate | `test_rejects[bad10]` |
| TestValidate | `test_rejects[bad11]` |
| TestValidate | `test_rejects[bad12]` |
| TestValidate | `test_rejects[bad13]` |
| TestValidate | `test_not_a_dict` |
| TestValidate | `test_control_characters_are_stripped` |
| TestValidate | `test_email_needs_consent` |
| TestValidate | `test_bad_or_injected_email[not-an-email]` |
| TestValidate | `test_bad_or_injected_email[a@b]` |
| TestValidate | `test_bad_or_injected_email[me@example.com\nBcc: victim@example.com]` |
| TestValidate | `test_bad_or_injected_email[me@example.com,other@example.com]` |
| TestValidate | `test_bad_or_injected_email[<me@example.com>]` |
| TestValidate | `test_bad_or_injected_email[email5]` |
| TestValidate | `test_diagnostics_allowlist_and_truncation` |
| — | `test_rate_limiter_window` |
| TestStore | `test_own_submissions_only_newest_first` |
| TestStore | `test_persists_and_survives_a_damaged_line` |
| TestStore | `test_votes_latest_wins` |
| TestStore | `test_concurrent_writes_do_not_corrupt` |
| TestFeedbackApi | `test_submit_and_list_own` |
| TestFeedbackApi | `test_validation_error` |
| TestFeedbackApi | `test_list_requires_valid_client` |
| TestFeedbackApi | `test_rate_limit_per_client` |
| TestFeedbackApi | `test_rate_limit_per_ip_even_with_new_client_ids` |
| TestFeedbackApi | `test_honeypot_drops_bots_silently` |
| TestFeedbackApi | `test_script_payload_is_stored_as_plain_text` |
| TestEmailDelivery | `test_new_feedback_is_emailed` |
| TestEmailDelivery | `test_recipient_addresses_never_reach_the_browser` |
| TestRoadmapApi | `test_list_and_vote` |
| TestRoadmapApi | `test_unknown_item_and_bad_client` |
| TestRoadmapApi | `test_garbage_client_param_is_ignored` |
| TestGuards | `test_cross_site_writes_are_blocked[headers0-/api/feedback-payload0]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers0-/api/jobs-payload1]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers0-/api/release-gpu-payload2]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers0-/api/support/roadmap/assistant/vote-payload3]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers0-/api/open-folder-payload4]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers1-/api/feedback-payload0]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers1-/api/jobs-payload1]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers1-/api/release-gpu-payload2]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers1-/api/support/roadmap/assistant/vote-payload3]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers1-/api/open-folder-payload4]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers2-/api/feedback-payload0]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers2-/api/jobs-payload1]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers2-/api/release-gpu-payload2]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers2-/api/support/roadmap/assistant/vote-payload3]` |
| TestGuards | `test_cross_site_writes_are_blocked[headers2-/api/open-folder-payload4]` |
| TestGuards | `test_same_origin_is_allowed` |
| TestGuards | `test_configured_extra_origin_is_allowed` |
| TestGuards | `test_oversized_body_is_rejected` |
| TestGuards | `test_security_headers` |

## Integration — owner e-mail notifications (19)

`tests/test_notify.py` · Stage 4 of `run_tests.ps1`

| Group | Test case |
|---|---|
| TestConfig | `test_disabled_without_settings` |
| TestConfig | `test_from_env` |
| TestConfig | `test_bad_config_rejected[kw0]` |
| TestConfig | `test_bad_config_rejected[kw1]` |
| TestConfig | `test_bad_config_rejected[kw2]` |
| TestConfig | `test_bad_config_rejected[kw3]` |
| TestConfig | `test_bad_config_rejected[kw4]` |
| TestMessage | `test_plain_text_with_everything_needed` |
| TestMessage | `test_no_reply_to_without_email` |
| TestMessage | `test_header_injection_through_title_is_impossible` |
| TestMessage | `test_hourly_cap` |
| — | `test_encrypted_connection_and_login[ssl-SMTP_SSL]` |
| — | `test_encrypted_connection_and_login[starttls-SMTP]` |
| — | `test_real_smtp_conversation_with_local_test_server` |
| — | `test_background_send_retries_then_reports` |
| — | `test_background_send_gives_up_without_crashing` |
| TestEnvFile | `test_loads_without_overriding` |
| TestEnvFile | `test_missing_file` |
| — | `test_secrets_are_never_committed` |

## Unit — Windows desktop launcher (10)

`tests/test_desktop.py` · Stage 3 of `run_tests.ps1`

| Group | Test case |
|---|---|
| — | `test_configure_environment_uses_bundled_resources` |
| — | `test_configure_environment_without_bundle_changes_nothing` |
| — | `test_user_override_of_models_is_respected` |
| — | `test_data_dir_is_per_user` |
| — | `test_bundle_dir_frozen_and_source` |
| — | `test_redirect_output_writes_log` |
| — | `test_port_detection_and_foreign_app` |
| — | `test_refuses_port_used_by_another_program` |
| — | `test_wait_until_ready_times_out_quickly` |
| — | `test_find_edge_returns_existing_path_or_none` |

## Unit — audio engine (87)

`tests/test_engine.py` · Stage 3 of `run_tests.ps1`

| Group | Test case |
|---|---|
| TestLoadAudio | `test_stereo_wav` |
| TestLoadAudio | `test_mp3_decodes_with_correct_duration` |
| TestLoadAudio | `test_mono_22k_is_resampled_and_upmixed` |
| TestLoadAudio | `test_audio_track_from_video` |
| TestLoadAudio | `test_mono_flag` |
| TestLoadAudio | `test_invalid_files_raise_user_error[spoofed_mp3]` |
| TestLoadAudio | `test_invalid_files_raise_user_error[png_as_wav]` |
| TestLoadAudio | `test_invalid_files_raise_user_error[empty]` |
| TestLoadAudio | `test_missing_file` |
| TestSaveAudio | `test_every_format_roundtrips[wav]` |
| TestSaveAudio | `test_every_format_roundtrips[mp3]` |
| TestSaveAudio | `test_every_format_roundtrips[flac]` |
| TestSaveAudio | `test_every_format_roundtrips[ogg]` |
| TestSaveAudio | `test_every_format_roundtrips[m4a]` |
| TestSaveAudio | `test_dots_in_names_are_kept[wav]` |
| TestSaveAudio | `test_dots_in_names_are_kept[mp3]` |
| TestSaveAudio | `test_wav_is_44k_stereo` |
| TestSaveAudio | `test_clipping_is_prevented` |
| TestSaveAudio | `test_mono_array_is_accepted` |
| — | `test_peaks` |
| — | `test_peaks_short_file` |
| — | `test_duration` |
| — | `test_job_dir_sanitises_names` |
| TestValidation | `test_choice_default_and_valid` |
| TestValidation | `test_choice_rejects[../../evil]` |
| TestValidation | `test_choice_rejects[exe]` |
| TestValidation | `test_choice_rejects[]` |
| TestValidation | `test_choice_rejects[None]` |
| TestValidation | `test_choice_rejects[WAV]` |
| TestValidation | `test_number[0-True]` |
| TestValidation | `test_number[5-True]` |
| TestValidation | `test_number[-1-False]` |
| TestValidation | `test_number[11-False]` |
| TestValidation | `test_number[x-False]` |
| TestValidation | `test_number[None-False]` |
| TestValidation | `test_number[nan-False]` |
| TestCut | `test_duration_and_fades` |
| TestCut | `test_end_zero_means_to_the_end` |
| TestCut | `test_end_past_length_is_clamped` |
| TestCut | `test_start_after_end_fails` |
| TestCut | `test_bad_format_fails` |
| TestJoin | `test_plain_concatenation` |
| TestJoin | `test_crossfade_shortens_by_overlap` |
| TestJoin | `test_mixed_formats` |
| TestJoin | `test_needs_two_files` |
| TestPitchTempo | `test_octave_up_doubles_frequency` |
| TestPitchTempo | `test_double_tempo_halves_duration_keeps_pitch` |
| TestPitchTempo | `test_tape_mode_speed_also_moves_pitch` |
| TestPitchTempo | `test_tape_mode_slow_down` |
| TestPitchTempo | `test_keep_pitch_must_be_boolean` |
| TestPitchTempo | `test_no_change_is_identity_length` |
| TestPitchTempo | `test_out_of_range[params0]` |
| TestPitchTempo | `test_out_of_range[params1]` |
| TestPitchTempo | `test_out_of_range[params2]` |
| TestEffects | `test_lofi_darkens_and_keeps_level_and_length` |
| TestEffects | `test_lofi_strength_scales` |
| TestEffects | `test_lofi_is_deterministic_and_zero_is_off` |
| TestEffects | `test_lofi_reduces_bit_depth` |
| TestEffects | `test_echo_repeats_at_the_right_time_and_level` |
| TestEffects | `test_echo_single_repeat_without_feedback` |
| TestEffects | `test_echo_mix_zero_is_off_and_never_clips` |
| TestEffects | `test_echo_tail_is_capped` |
| TestEffects | `test_pitch_tool_with_lofi_and_echo` |
| TestEffects | `test_effects_only_without_speed_or_pitch_change` |
| TestEffects | `test_effect_values_are_validated[params0]` |
| TestEffects | `test_effect_values_are_validated[params1]` |
| TestEffects | `test_effect_values_are_validated[params2]` |
| TestEffects | `test_effect_values_are_validated[params3]` |
| TestEffects | `test_effect_values_are_validated[params4]` |
| TestEffects | `test_effect_values_are_validated[params5]` |
| TestEffects | `test_effect_values_are_validated[params6]` |
| TestAnalyze | `test_key_of_a_major_triad` |
| TestAnalyze | `test_bpm_of_120_click_track` |
| TestAnalyze | `test_percussion_reports_no_key_without_nan` |
| TestAnalyze | `test_camelot_table_is_complete` |
| TestConvert | `test_convert[flac]` |
| TestConvert | `test_convert[mp3]` |
| TestConvert | `test_convert[m4a]` |
| TestMix | `test_volumes_are_applied` |
| TestMix | `test_all_muted` |
| TestMix | `test_path_outside_output_is_rejected` |
| TestMix | `test_traversal_path_is_rejected` |
| TestMix | `test_bad_input_shapes` |
| — | `test_separate_rejects_bad_options` |
| — | `test_progress_hook_maps_tqdm_to_range` |
| — | `test_progress_hook_silent_when_inactive` |
| — | `test_hooks_are_installed` |

## Unit — model wrappers (stand-in models) (24)

`tests/test_engine_models.py` · Stage 3 of `run_tests.ps1`

| Group | Test case |
|---|---|
| — | `test_demucs_four_stems` |
| — | `test_demucs_six_stem_model_name` |
| — | `test_demucs_model_is_cached` |
| — | `test_demucs_progress_spans_all_passes` |
| — | `test_demucs_gpu_out_of_memory_falls_back_to_cpu` |
| — | `test_demucs_fails_cleanly_when_no_device_works` |
| — | `test_separate_demucs_two_stem_sums_instrumental` |
| — | `test_separate_demucs_orders_stems` |
| — | `test_roformer_outputs_and_cleanup[False]` |
| — | `test_roformer_outputs_and_cleanup[True]` |
| — | `test_roformer_first_run_says_downloading` |
| — | `test_roformer_existing_model_says_loading` |
| — | `test_roformer_is_cached_and_speed_changes_without_reload` |
| — | `test_switching_models_unloads_the_previous_one` |
| — | `test_roformer_load_failure_becomes_user_error[exc0]` |
| — | `test_roformer_load_failure_becomes_user_error[exc1]` |
| — | `test_roformer_separation_failure_becomes_user_error[exc0]` |
| — | `test_roformer_separation_failure_becomes_user_error[exc1]` |
| — | `test_separate_roformer_end_to_end` |
| — | `test_gpu_name_cpu` |
| — | `test_gpu_name_from_nvidia_smi` |
| — | `test_gpu_name_when_nvidia_smi_missing` |
| — | `test_models_loaded_reports_state` |
| — | `test_free_gpu_moves_demucs_to_cpu` |

## GPU worker — real model inference (12)

`tests/test_gpu.py` · Stage 8 of `run_tests.ps1`

| Group | Test case |
|---|---|
| — | `test_two_stem_engines[opts0]` |
| — | `test_two_stem_engines[opts1]` |
| — | `test_two_stem_engines[opts2]` |
| — | `test_demucs_multistem[4]` |
| — | `test_demucs_multistem[6]` |
| — | `test_progress_is_real[opts0]` |
| — | `test_progress_is_real[opts1]` |
| — | `test_gpu_memory_is_released_between_engines` |
| — | `test_speed_setting_changes_overlap` |
| — | `test_worker_process_returns_all_gpu_memory` |
| — | `test_silence_in_silence_out` |
| — | `test_pure_tone_is_not_distorted` |

## Unit — GPU worker process (8)

`tests/test_worker.py` · Stage 3 of `run_tests.ps1`

| Group | Test case |
|---|---|
| — | `test_runs_a_job_and_streams_progress` |
| — | `test_worker_is_reused_between_jobs` |
| — | `test_user_error_keeps_its_type` |
| — | `test_unexpected_error_becomes_runtime_error` |
| — | `test_stop_ends_the_process` |
| — | `test_crash_mid_job_is_reported_and_next_job_recovers` |
| — | `test_worker_exits_when_parent_is_killed` |
| — | `test_parent_never_initialises_cuda` |

## Requirement traceability

| Policy requirement | Covered by |
|---|---|
| API endpoints, request/response validation | `test_api.py::TestJobs`, `TestUpload`, `test_index_page`, `test_info` |
| File upload validation, MIME spoofing, size limit | `TestUpload::test_mime_spoofing_is_rejected`, `test_size_limit`, `test_empty_file`, `test_zero_length_audio_is_rejected` |
| Path traversal | `TestUpload::test_path_traversal_filename_is_neutralised`, `TestFiles::test_static_path_traversal`, `TestMix::test_traversal_path_is_rejected`, `test_open_folder_outside_output_is_refused`, `TestJobs::test_raw_file_paths_cannot_be_injected` |
| Secret exposure, network exposure | `test_info_leaks_no_secrets`, `test_server_only_listens_on_localhost` |
| Audio processing services | `test_engine.py` (all), `test_engine_models.py` |
| Job queue behaviour | `test_jobs_run_one_at_a_time_in_order`, `test_progress_is_monotonic_and_has_eta`, `test_progress_never_goes_backwards`, `test_finished_jobs_are_pruned` |
| GPU worker execution | `test_gpu.py` (all) |
| Worker failure / error handling | `test_unexpected_exception_is_reported`, `test_validation_error_is_reported_on_job`, `test_roformer_load_failure_becomes_user_error`, `test_roformer_separation_failure_becomes_user_error`, `test_demucs_gpu_out_of_memory_falls_back_to_cpu`, `test_demucs_fails_cleanly_when_no_device_works` |
| File deletion / temp cleanup | `test_delete_upload`, `test_removing_file_deletes_upload`, `test_size_limit` (no leftovers), `test_roformer_outputs_and_cleanup`, `TestSaveAudio::test_every_format_roundtrips` (no `.tmp.wav`), `test_clean_temp_files_only_on_explicit_call`, `test_importing_server_never_deletes_files` |
| Output duration, sample rate, channels, encoding | `TestSaveAudio`, `TestCut`, `TestJoin`, `TestPitchTempo`, `TestConvert`, `test_every_format_in_worker_thread`, `test_two_stem_engines` |
| Audio effects (lo-fi, echo) | `TestEffects` (level, length, bit depth, echo timing, tail cap), `test_effect_controls_disabled_until_switched_on`, `test_effect_presets`, `test_live_lofi_and_echo_preview`, `test_render_with_lofi_and_echo` |
| Clipping, distortion | `test_clipping_is_prevented`, `test_pure_tone_is_not_distorted`, benchmark clipping check |
| Vocal / instrument leakage, separation quality | `test_two_stem_engines`, `test_demucs_multistem`, `benchmarks/audio_quality.py` |
| GPU memory | `test_gpu_memory_is_released_between_engines`, `test_two_stem_engines` (< 3800 MB), benchmark |
| Upload UI, audio player, waveform, mixer, controls | `test_cut_flow`, `test_join_reorder_and_join`, `test_split_with_live_progress_and_mixer` |
| Loading and failure states | `test_cut_flow` (progress → done), `test_job_failure_state`, `test_spoofed_upload_shows_error` |
| Responsive layouts | `test_responsive_no_horizontal_scroll` (375, 768, 1440 px), theme page-width tests |
| Accessibility | `test_every_control_has_an_accessible_name`, `test_keyboard_opens_file_picker`, `test_images_and_lang` |
| Browser compatibility | whole UI suite in Chromium and Microsoft Edge (Firefox blocked, see `progress.md`) |
| Concurrency / throughput | `test_concurrent_requests` (50 requests, p95 bound) |
