from fd6.shapegen.profile import Profile, load_profile


def test_full_profile_options_round_trip():
    original = Profile(
        name="custom",
        description="Custom logo profile",
        max_preview_size=900,
        max_resolution=1536,
        max_threads=1,
        mutated_samples=1200,
        posterize_levels=192,
        preview_every=10,
        random_samples=6000,
        redundant_check_every=250,
        save_at=[500, 1000, 1500, 2000, 2500],
        save_every=50,
        stop_at=2500,
        shape_types=["rotated_rectangle", "rotated_ellipse"],
        compute_backend="cpu",
        preserve_transparency=True,
        cap_generation_2048=False,
    )

    loaded = load_profile("roundtrip", original.to_ini())

    assert loaded.max_preview_size == 900
    assert loaded.max_resolution == 1536
    assert loaded.max_threads == 1
    assert loaded.mutated_samples == 1200
    assert loaded.posterize_levels == 192
    assert loaded.preview_every == 10
    assert loaded.random_samples == 6000
    assert loaded.redundant_check_every == 250
    assert loaded.save_at == [500, 1000, 1500, 2000, 2500]
    assert loaded.save_every == 50
    assert loaded.stop_at == 2500
    assert loaded.shape_types == ["rotated_rectangle", "rotated_ellipse"]
    assert loaded.compute_backend == "cpu"
    assert loaded.preserve_transparency is True
    assert loaded.cap_generation_2048 is False


def test_old_profiles_keep_backward_compatible_image_defaults():
    loaded = load_profile("legacy", "[profile]\nstopAt=500\n")
    assert loaded.stop_at == 500
    assert loaded.preserve_transparency is False
    assert loaded.cap_generation_2048 is False
